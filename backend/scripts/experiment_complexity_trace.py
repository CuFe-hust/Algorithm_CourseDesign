"""Offline accuracy, repeatability and cost evaluation of the trace complexity route.

The script replays the production path (``probe`` -> ``collect`` -> ``infer``) on
the reference solutions of the 70-problem bank, compares the published time
class against the hand-labelled ground truth in
``data/analysis/complexity_expected_classes.json`` and writes one evidence JSON.

It reads only the question bank and the seeded profile table: no database
session, no network, no judge service. Run it from ``backend``::

    ../.venv/bin/python -m scripts.experiment_complexity_trace --language python

``--language cpp`` uses the native adapter. That adapter is shipped separately,
so a missing toolchain or a broken adapter is recorded per problem as an error
instead of aborting the run.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analysis import probe, profiles  # noqa: E402
from app.analysis.trace import collect, infer  # noqa: E402
from app.analysis.trace.classes import TIME_CLASSES  # noqa: E402

QUESTION_BANK = REPO_ROOT / 'data' / 'formatted' / 'questions.programming.json'
LABEL_FILE = REPO_ROOT / 'data' / 'analysis' / 'complexity_expected_classes.json'
DEFAULT_OUTPUT = (REPO_ROOT / 'docs' / 'implementation' / 'evidence' /
                  'similarity-complexity' / '2026-10-29-trace-experiments.json')

# CLI name -> (language handed to collect, language tag in the bank, display name).
LANGUAGES = {
    'python': ('python3', 'Python', 'Python 3'),
    'cpp': ('cpp', 'C++', 'C++17'),
}
NOT_MEASURABLE_FAMILIES = ('EXISTING_CASES', 'FIXED')
COLLECT_BUDGET_MS = 30_000
ERROR_CLASS = 'ERROR'
MAX_STDOUT_FAILURES = 15
SEED = profiles.VALIDATION_SEED


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Offline evaluation of the trace-based complexity route over the question bank.')
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT),
                        help='evidence JSON path (default: %(default)s)')
    parser.add_argument('--language', choices=tuple(LANGUAGES), default='python',
                        help='language of the reference solutions to measure (default: python)')
    parser.add_argument('--codes', default='',
                        help='comma separated problem codes; default is every problem in the bank')
    parser.add_argument('--repeat', type=int, default=2,
                        help='how many times the whole ladder is collected per problem (default: 2)')
    parser.add_argument('--seed', type=int, default=SEED,
                        help='input generation seed (default: %(default)s)')
    parser.add_argument('--compare', default='',
                        help='another evidence JSON to compare predicted classes against')
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error('--repeat 必须大于等于 1')
    return args


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _reference_source(entry: dict, reference_language: str) -> str | None:
    for solution in entry.get('reference_solutions') or []:
        if solution.get('language') == reference_language:
            return solution.get('content')
    return None


def _collect_once(source: str, collect_language: str, family: str, spec: dict,
                  seed: int) -> tuple[object, object]:
    trace = collect.collect(source, collect_language, family, spec,
                            seed=seed, budget_ms=COLLECT_BUDGET_MS)
    conclusion = infer.infer(trace, language_label=collect.language_label(collect_language))
    return trace, conclusion


def _points_payload(trace) -> list[dict]:
    return [{'n': point.n,
             'work': round(float(point.work), 3),
             'baseline_work': round(float(point.baseline_work), 3),
             'peak_bytes': point.peak_bytes}
            for point in trace.ok_points]


def _ladder_failure(trace) -> str | None:
    """Describe the first rung that did not finish normally, if any."""
    for point in trace.points:
        if point.verdict != 'OK':
            detail = (point.detail or '没有细节').strip().splitlines()
            return f'n={point.n} {point.verdict}: {detail[-1][:160] if detail else "没有细节"}'
    return None


def _repeat_consistency(first: list[dict], second: list[dict]) -> tuple[bool | None, list[dict]]:
    """Compare per-rung work of two ladder runs; exact counts must agree."""
    first_work = {row['n']: row['work'] for row in first}
    second_work = {row['n']: row['work'] for row in second}
    shared = sorted(set(first_work) & set(second_work))
    if not shared:
        return None, []
    mismatches = []
    for size in shared:
        left, right = first_work[size], second_work[size]
        if left == right:
            continue
        mismatch = {'n': size, 'first': left, 'second': right, 'delta': round(right - left, 3)}
        if left:
            mismatch['delta_ratio'] = round(abs(right - left) / left, 6)
        mismatches.append(mismatch)
    return not mismatches, mismatches


def _evaluate_one(code: str, entry: dict, label: dict, language: str,
                  reference_language: str, seed: int, repeat: int) -> dict:
    """Measure one problem, returning a result row that is always JSON-safe."""
    started = time.monotonic()
    result = {
        'code': code,
        'title': entry.get('title', ''),
        'family': None,
        'expected': label.get('expected') if label else None,
        'expected_confidence': label.get('confidence') if label else None,
        'rationale': label.get('rationale') if label else None,
        'predicted': ERROR_CLASS,
        'confidence': None,
        'method': None,
        'recurrence': None,
        'closed_form': None,
        'notes': [],
        'limitations': [],
        'points': [],
        'rungs_planned': 0,
        'rungs_ok': 0,
        'stop_reason': None,
        'deterministic_repeat': None,
        'repeat_mismatches': [],
        'adapter_deterministic': None,
        'elapsed_seconds': 0.0,
        'verdict': 'error',
        'error': None,
    }

    profile = profiles.PROFILES.get(code)
    if profile is None:
        family, spec = 'EXISTING_CASES', {}
        reason = profiles.NOT_SCALABLE.get(code, profiles.DEFAULT_NOT_SCALABLE_REASON)
    else:
        family, spec = profile
        reason = profiles.NOT_SCALABLE.get(code)
    result['family'] = family

    if reason is not None or family in NOT_MEASURABLE_FAMILIES:
        result.update({
            'predicted': 'UNKNOWN',
            'verdict': 'not_measurable',
            'error': reason or 'profile 为 EXISTING_CASES，没有可伸缩输入',
            'elapsed_seconds': round(time.monotonic() - started, 3),
        })
        return result

    source = _reference_source(entry, reference_language)
    if not source:
        result.update({
            'error': f'题库没有 {reference_language} 参考解',
            'elapsed_seconds': round(time.monotonic() - started, 3),
        })
        return result

    collect_language = LANGUAGES[language][0]
    try:
        adapter = collect.adapter_for(collect_language)
    except Exception as error:  # noqa: BLE001 - a broken adapter is a data point, not a crash
        adapter = None
        result['error'] = f'采集器不可用：{type(error).__name__}: {error}'
    if adapter is None and result['error'] is None:
        result['error'] = f'{collect_language} 采集器不可用（adapter_for 返回 None）'
    if result['error'] is not None:
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        return result

    try:
        result['rungs_planned'] = len(probe.ladder(family, seed, spec))
    except Exception:  # noqa: BLE001 - planning is part of what is under test
        result['rungs_planned'] = 0

    runs: list[object] = []
    conclusion = None
    try:
        for _ in range(repeat):
            trace, conclusion = _collect_once(source, collect_language, family, spec, seed)
            runs.append(trace)
        first = runs[0]
        payload = conclusion.time.to_payload()
        result.update({
            'predicted': payload.get('class'),
            'confidence': payload.get('confidence'),
            'method': payload.get('method'),
            'recurrence': payload.get('recurrence'),
            'closed_form': payload.get('closed_form'),
            'notes': payload.get('notes') or [],
            'limitations': list(getattr(conclusion, 'limitations', []) or []),
            'points': _points_payload(first),
            'rungs_ok': len(first.ok_points),
            'stop_reason': first.stop_reason,
            'adapter_deterministic': first.deterministic,
        })
        if len(runs) >= 2:
            consistent, mismatches = _repeat_consistency(_points_payload(runs[0]),
                                                        _points_payload(runs[1]))
            result['deterministic_repeat'] = consistent
            result['repeat_mismatches'] = mismatches
        if not first.ok_points:
            result['verdict'] = 'error'
            result['error'] = _ladder_failure(first) or f'没有任何完成的档位（{first.stop_reason}）'
        else:
            result['verdict'] = 'ok'
            failure = _ladder_failure(first)
            if failure is not None:
                result['error'] = f'档位中断：{failure}'
    except Exception as error:  # noqa: BLE001 - one failed problem must not stop the run
        result.update({
            'verdict': 'error',
            'predicted': ERROR_CLASS,
            'error': f'{type(error).__name__}: {error}',
        })
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return result


def _classify_failure(row: dict) -> str:
    if row['verdict'] == 'not_measurable':
        return 'not_measurable'
    if row['verdict'] == 'error':
        message = row.get('error') or ''
        if '采集器不可用' in message or 'adapter_for 返回 None' in message:
            return 'adapter_unavailable'
        if '参考解' in message:
            return 'no_reference_solution'
        if '档位中断' not in message and row.get('rungs_ok', 0) == 0:
            stop_reason = (row.get('stop_reason') or '').upper()
            if stop_reason == 'TIME_LIMIT_EXCEEDED':
                return 'time_limit'
            if stop_reason == 'COMPILATION_ERROR':
                return 'compile_error'
            if stop_reason in ('RUNTIME_ERROR',):
                return 'runtime_error'
            if stop_reason in ('', 'BUDGET_EXHAUSTED', 'NO_LADDER'):
                return 'budget_or_ladder'
            return 'execution_error'
        if '档位中断' in message:
            return 'partial_ladder'
        return 'collect_exception'
    if row.get('predicted') == 'UNKNOWN':
        return 'predicted_unknown'
    if row.get('predicted') != row.get('expected'):
        return 'wrong_class'
    return 'correct'


def _summary(results: list[dict], language: str, seed: int, repeat: int,
             compare: dict | None) -> dict:
    labeled = [row for row in results if row.get('expected') in TIME_CLASSES]
    measured_labeled = [row for row in labeled if row['verdict'] == 'ok']
    correct = [row for row in labeled if row['predicted'] == row['expected']]
    confusion: dict[str, dict[str, int]] = {}
    for row in labeled:
        expected = row['expected']
        predicted = row['predicted'] or ERROR_CLASS
        confusion.setdefault(expected, {})
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1
    pairs = [(expected, predicted, count)
             for expected, row in confusion.items()
             for predicted, count in row.items() if expected != predicted]
    pairs.sort(key=lambda item: (-item[2], item[0], item[1]))

    by_class = {}
    for name in TIME_CLASSES:
        rows = [row for row in labeled if row['expected'] == name]
        if not rows:
            continue
        by_class[name] = {
            'labeled': len(rows),
            'correct': sum(1 for row in rows if row['predicted'] == name),
            'predicted': dict(confusion.get(name, {})),
        }

    repeatable = [row for row in results if row['deterministic_repeat'] is not None]
    deterministic = [row for row in repeatable if row['deterministic_repeat']]
    repeat_mismatches = [{'code': row['code'], 'mismatches': row['repeat_mismatches']}
                         for row in repeatable if not row['deterministic_repeat']]

    elapsed = [row['elapsed_seconds'] for row in results]
    costs = {
        'problems': len(elapsed),
        'min': round(min(elapsed), 3) if elapsed else None,
        'median': round(statistics.median(elapsed), 3) if elapsed else None,
        'max': round(max(elapsed), 3) if elapsed else None,
        'total': round(sum(elapsed), 3),
    }

    buckets: Counter[str] = Counter()
    failures = []
    for row in results:
        bucket = _classify_failure(row)
        buckets[bucket] += 1
        if bucket == 'correct':
            continue
        failures.append({
            'code': row['code'],
            'title': row['title'],
            'bucket': bucket,
            'verdict': row['verdict'],
            'expected': row['expected'],
            'predicted': row['predicted'],
            'stop_reason': row['stop_reason'],
            'error': row['error'],
        })

    not_measurable = [{'code': row['code'], 'reason': row['error'], 'family': row['family']}
                      for row in results if row['verdict'] == 'not_measurable']
    unknown_expected = [{'code': row['code'], 'rationale': row['rationale'],
                         'predicted': row['predicted'], 'error': row['error']}
                        for row in results if row['expected'] == 'UNKNOWN']

    summary = {
        'total_problems': len(results),
        'labeled': len(labeled),
        'labeled_measured': len(measured_labeled),
        'correct': len(correct),
        'accuracy': round(len(correct) / len(labeled), 4) if labeled else None,
        'accuracy_measured': (round(sum(1 for row in measured_labeled
                                        if row['predicted'] == row['expected'])
                                    / len(measured_labeled), 4)
                              if measured_labeled else None),
        'errors': sum(1 for row in results if row['verdict'] == 'error'),
        'not_measurable': len(not_measurable),
        'confusion': confusion,
        'top_confusions': [{'expected': expected, 'predicted': predicted, 'count': count}
                           for expected, predicted, count in pairs[:3]],
        'by_expected_class': by_class,
        'not_measurable_items': not_measurable,
        'unknown_expected': unknown_expected,
        'repeatability': {
            'runs_per_problem': repeat,
            'compared': len(repeatable),
            'deterministic': len(deterministic),
            'ratio': round(len(deterministic) / len(repeatable), 4) if repeatable else None,
            'mismatches': repeat_mismatches,
        },
        'cost_seconds': costs,
        'failures': {
            'by_bucket': dict(sorted(buckets.items())),
            'items': failures,
        },
        'language': language,
        'seed': seed,
    }

    if compare is not None:
        other_rows = {row['code']: row for row in compare.get('results') or []}
        both = []
        for row in results:
            other = other_rows.get(row['code'])
            if other is None:
                continue
            if row['verdict'] != 'ok' or other.get('verdict') != 'ok':
                continue
            both.append((row, other))
        agreements = [1 for row, other in both if row['predicted'] == other.get('predicted')]
        disagreements = [{
            'code': row['code'],
            'expected': row['expected'],
            'this': row['predicted'],
            'other': other.get('predicted'),
        } for row, other in both if row['predicted'] != other.get('predicted')]
        summary['cross_language'] = {
            'other_language': compare.get('meta', {}).get('language'),
            'compared': len(both),
            'agree': len(agreements),
            'ratio': round(len(agreements) / len(both), 4) if both else None,
            'disagreements': disagreements,
        }
    return summary


def _build_payload(results: list[dict], args: argparse.Namespace, labels: dict,
                   compare: dict | None, started: float) -> dict:
    summary = _summary(results, args.language, args.seed, args.repeat, compare)
    seen = [row['code'] for row in results]
    return {
        'meta': {
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'python': platform.python_version(),
            'platform': platform.platform(),
            'language': args.language,
            'reference_language': LANGUAGES[args.language][1],
            'collect_language': LANGUAGES[args.language][0],
            'language_label': LANGUAGES[args.language][2],
            'seed': args.seed,
            'repeat': args.repeat,
            'collect_budget_ms': COLLECT_BUDGET_MS,
            'wall_seconds': round(time.monotonic() - started, 3),
            'question_bank': str(QUESTION_BANK.relative_to(REPO_ROOT)),
            'label_file': str(LABEL_FILE.relative_to(REPO_ROOT)),
            'codes': args.codes or 'ALL',
            'problems': len(seen),
            'notes': [
                '只读题库与 PROFILES，不连数据库、不联网；采集与推断走生产代码路径',
                'expected 取 TIME_CLASSES 的题计入准确率；UNKNOWN 与 NOT_MEASURABLE 不计入分母',
                '跨语言一致性需要先用另一种语言跑一遍，再用 --compare 读取那份 JSON',
                '按档位比较的 work 是精确计数，可重复性要求两份结果逐档完全相等',
            ],
        },
        'labels': {row['code']: {'expected': labels[row['code']]['expected'],
                                 'confidence': labels[row['code']]['confidence'],
                                 'rationale': labels[row['code']]['rationale']}
                   for row in results if row['code'] in labels},
        'results': results,
        'summary': summary,
    }


def _write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    temporary.replace(path)


def _print_summary(summary: dict, results: list[dict]) -> None:
    repeat = summary['repeatability']
    cost = summary['cost_seconds']
    print('SUMMARY '
          f'labeled={summary["labeled"]} correct={summary["correct"]} '
          f'accuracy={summary["accuracy"]} '
          f'accuracy_measured={summary["accuracy_measured"]} '
          f'errors={summary["errors"]} not_measurable={summary["not_measurable"]} '
          f'repeat_deterministic={repeat["deterministic"]}/{repeat["compared"]} '
          f'cost_s={cost["min"]}/{cost["median"]}/{cost["max"]} '
          f'language={summary["language"]} seed={summary["seed"]}')
    lines = 0
    for item in summary['failures']['items']:
        if lines >= MAX_STDOUT_FAILURES:
            print(f'... 其余 {len(summary["failures"]["items"]) - lines} 条失败见 evidence JSON')
            break
        detail = (item['error'] or '').replace('\n', ' ')[:160]
        print(f'FAIL {item["code"]} {item["bucket"]}: expected={item["expected"]} '
              f'predicted={item["predicted"]} {detail}')
        lines += 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()

    labels = _load_json(LABEL_FILE)
    bank = {entry['code']: entry for entry in _load_json(QUESTION_BANK)}
    wanted = [code.strip() for code in args.codes.split(',') if code.strip()] or list(bank)
    missing = [code for code in wanted if code not in bank]
    if missing:
        print(f'题库里没有这些题号：{", ".join(missing)}', file=sys.stderr)
        return 2

    compare = _load_json(Path(args.compare)) if args.compare else None
    reference_language = LANGUAGES[args.language][1]
    results: list[dict] = []
    for index, code in enumerate(wanted, start=1):
        entry = bank[code]
        row = _evaluate_one(code, entry, labels.get(code) or {}, args.language,
                            reference_language, args.seed, args.repeat)
        results.append(row)
        print(f'[{index}/{len(wanted)}] {code} {row["verdict"]} '
              f'expected={row["expected"]} predicted={row["predicted"]} '
              f'rungs={row["rungs_ok"]}/{row["rungs_planned"]} '
              f'{row["elapsed_seconds"]}s', flush=True)
        _write_payload(Path(args.output), _build_payload(results, args, labels, compare, started))

    payload = _build_payload(results, args, labels, compare, started)
    _write_payload(Path(args.output), payload)
    _print_summary(payload['summary'], results)
    print(f'证据已写入 {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
