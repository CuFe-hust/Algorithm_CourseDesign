"""Check every seeded input family against the bank's own reference solution.

Offline check: it reads the question bank JSON, walks ``app.analysis.profiles.PROFILES``
and calls ``validate_profile`` for each problem. No database connection, no
network, no writes. Each problem executes the reference solution over the whole
generated ladder with the same tracer students are measured with, so the printed
verdict is exactly what seeding would store.

    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles
    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles --json
    cd backend && ../.venv/bin/python -m scripts.validate_complexity_profiles --only CODE-P07,CODE-P45

Exit code is 0 when every measurable problem passes and 1 otherwise, so the
script can be used as a coverage gate.
"""
import argparse
import json
import time

from app.analysis.profiles import NOT_SCALABLE, PROFILES, QUESTION_BANK, validate_profile

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
    arguments = parser.parse_args()

    entries = json.loads(QUESTION_BANK.read_text(encoding='utf-8'))
    bank = {entry['code']: entry.get('reference_solutions') or [] for entry in entries}
    codes = [entry['code'] for entry in entries]
    if arguments.only:
        wanted = {part.strip() for part in arguments.only.split(',') if part.strip()}
        codes = [code for code in codes if code in wanted]

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
