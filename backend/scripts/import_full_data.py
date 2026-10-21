import argparse
import json
from pathlib import Path
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.full_data_import import load_snapshot, import_snapshot


def main():
    parser = argparse.ArgumentParser(description='Import full questions and an explicit roster into the project database.')
    parser.add_argument('--students-file', type=Path)
    parser.add_argument('--allow-private', action='store_true')
    args = parser.parse_args()
    questions, roster = load_snapshot(students_file=args.students_file, allow_private=args.allow_private)
    engine = make_engine()
    try:
        with Session(engine) as session, session.begin():
            result = import_snapshot(session, questions, roster)
        print(json.dumps(result, ensure_ascii=True))
    except Exception:
        # SQLAlchemy exceptions can embed input parameters, including real identities.
        raise SystemExit('Import failed and rolled back. Check snapshot, migration and identity mode; no identity details logged.') from None
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
