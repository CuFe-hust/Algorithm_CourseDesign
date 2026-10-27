"""Complexity analysis worker.

Claims PENDING complexity reports, runs the measured size ladder outside the
transaction, and writes the verdict back under the same lease fencing the judge
uses. Kept as a separate process from the code judge so an expensive measurement
never delays a student's verdict.
"""
import argparse
import json
import time

from sqlalchemy.orm import Session

from app.analysis import complexity_service
from app.db.session import make_engine


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true', help='持续运行，直到 Ctrl+C')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--static-only', action='store_true', help='只做结构分析，不执行测量')
    parser.add_argument('--recover', action='store_true', help='立即回收过期租约后退出')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000:
        parser.error('--limit must be 1..1000')
    engine = make_engine()
    processed = 0
    try:
        if args.recover:
            with Session(engine) as db:
                recovered = complexity_service.recover_expired(db)
            print(json.dumps({'recovered': recovered}), flush=True)
            return 0
        while True:
            with Session(engine) as db:
                worked = 0
                for _ in range(args.limit):
                    if not complexity_service.process_one(db, measure=not args.static_only):
                        break
                    worked += 1
            processed += worked
            if not args.watch:
                break
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()
    print(json.dumps({'processed': processed, 'worker': 'complexity-only'}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
