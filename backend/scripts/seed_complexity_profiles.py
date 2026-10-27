"""Seed the per-problem scale ladder used by the complexity worker.

Run once after ``alembic upgrade head`` and after the demo or full data import:

    python -m scripts.seed_complexity_profiles
"""
import json

from sqlalchemy.orm import Session

from app.analysis.profiles import seed_profiles
from app.db.session import make_engine


def main() -> int:
    engine = make_engine()
    try:
        with Session(engine) as db:
            result = seed_profiles(db)
    finally:
        engine.dispose()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
