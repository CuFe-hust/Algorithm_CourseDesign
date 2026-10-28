"""Seed the per-problem scale ladder used by the complexity worker.

Run once after ``alembic upgrade head`` and after the demo or full data import:

    python -m scripts.seed_complexity_profiles
"""
import argparse
import json

from sqlalchemy.orm import Session

from app.analysis.profiles import seed_profiles
from app.db.session import make_engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-validate', action='store_true',
                        help='跳过伸缩档验收（不建议；验收用题库参考解，成本每题不到一秒）')
    parser.add_argument('--revalidate', action='store_true',
                        help='重新验收已入库的种子伸缩档，错配的降级为仅结构分析')
    arguments = parser.parse_args()
    engine = make_engine()
    try:
        with Session(engine) as db:
            if arguments.revalidate:
                from app.analysis.profiles import revalidate_profiles
                result = revalidate_profiles(db)
            else:
                result = seed_profiles(db, validate=not arguments.no_validate)
    finally:
        engine.dispose()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
