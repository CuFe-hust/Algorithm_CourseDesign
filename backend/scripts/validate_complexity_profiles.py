"""Check every seeded input family against the bank's own reference solution.

The default offline check reads the question bank JSON, walks
``app.analysis.profiles.PROFILES`` and calls ``validate_profile`` for each problem.
It executes references with the same tracer used for students. ``--adaptive``
bypasses all problem-code mappings, infers layouts from input descriptions and
constraints, and validates generated inputs with reference execution and known
answers. Neither mode connects to the database.

    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles
    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles --json
    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles --only CODE-P07,CODE-P45
    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles --adaptive --json

Default mode exits 1 on validation failure and 0 otherwise. Adaptive mode exits
0 after a completed coverage experiment; unsupported formats are in its JSON.
"""
import argparse
import json
import time
from types import SimpleNamespace

from app.analysis.profiles import (NOT_SCALABLE, PROFILES, QUESTION_BANK, adaptive_candidates,
                                   validate_adaptive, validate_profile)

# Families that describe "no scalable input", not an input format: they are
# reported as skipped rather than as a pass or a failure.
UNSCALABLE_FAMILIES = ('FIXED', 'EXISTING_CASES')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true',
                        help='输出机读结果（JSON），不打印逐题进度行')
    parser.add_argument('--only', default='',
                        help='逗号分隔的题号，只检查这些题（默认全部）')
    parser.add_argument('--adaptive', action='store_true',
                        help='禁用题号映射，从输入说明、约束和测试用例自动发现并真实验收生成方案')
    arguments = parser.parse_args()

    entries = json.loads(QUESTION_BANK.read_text(encoding='utf-8'))
    bank = {entry['code']: entry.get('reference_solutions') or [] for entry in entries}
    codes = [entry['code'] for entry in entries]
    if arguments.only:
        wanted = {part.strip() for part in arguments.only.split(',') if part.strip()}
        codes = [code for code in codes if code in wanted]

    if arguments.adaptive:
        passed, unsupported = [], []
        started = time.monotonic()
        for entry in entries:
            if entry['code'] not in codes:
                continue
            version = SimpleNamespace(input_spec_md=entry.get('input'), data_constraints_md=entry.get('constraints'))
            cases = [(case['input'], case['output']) for case in entry.get('tests', [])]
            references = [(reference.get('language', ''), reference['content'])
                          for reference in entry.get('reference_solutions', [])]
            candidates, reason = adaptive_candidates(version, cases)
            spec = None
            for candidate in candidates:
                spec, reason = validate_adaptive(candidate, references, cases)
                if spec is not None:
                    passed.append({'code': entry['code'], 'family': candidate['family'],
                                   'sizes': spec['sizes'], 'scale': spec['scale'],
                                   'distributions': spec.get('distributions', ['random'])})
                    break
            if spec is None:
                unsupported.append({'code': entry['code'], 'reason': reason})
            if not arguments.json:
                print(f'{"ok  " if spec else "skip"} {entry["code"]} {reason}', flush=True)
        result = {'mode': 'adaptive-without-code-mapping', 'total': len(codes),
                  'passed': len(passed), 'profiles': passed, 'unsupported': unsupported,
                  'seconds': round(time.monotonic() - started, 1)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    passed: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []
    missing: list[str] = []
    started = time.monotonic()
    for code in codes:
        if code not in PROFILES:
            missing.append(code)
            continue
        family, spec = PROFILES[code]
        if family in UNSCALABLE_FAMILIES or code in NOT_SCALABLE:
            skipped.append({'code': code, 'family': family,
                            'reason': NOT_SCALABLE.get(code, '固定输入或没有可伸缩的输入格式')})
            continue
        began = time.monotonic()
        ok, reason = validate_profile(bank, code, family, spec)
        seconds = round(time.monotonic() - began, 2)
        record = {'code': code, 'family': family, 'spec': spec, 'seconds': seconds}
        if ok:
            passed.append(record)
        else:
            record['reason'] = reason
            failed.append(record)
        if not arguments.json:
            stamp = f'{seconds:5.2f}s'
            print(f'{"ok  " if ok else "FAIL"} {code} {family:<26} {stamp}'
                  + ('' if ok else f'  {reason}'))

    checked = len(passed) + len(failed)
    result = {
        'total': len(codes),
        'checked': checked,
        'passed': len(passed),
        'failed': failed,
        'skipped': skipped,
        'missing_from_profiles': missing,
        'seconds': round(time.monotonic() - started, 1),
    }
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print()
        print(f'通过 {len(passed)}/{checked} 道可测题'
              f'（题库 {len(codes)} 道，不可伸缩跳过 {len(skipped)} 道）')
        if missing:
            print('题库中有、但伸缩档表里没有的题：' + '、'.join(missing))
        if failed:
            print('失败清单：')
            for record in failed:
                print(f'  {record["code"]}（{record["family"]}）：{record["reason"]}')
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
