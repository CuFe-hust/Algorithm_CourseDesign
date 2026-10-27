"""Analysis worker only. It never claims JUDGE jobs or executes student code."""
import argparse
import json
import time
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.analysis.framework.runner import process_one


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--limit',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.limit<=1000:parser.error('--limit must be 1..1000')
    engine=make_engine();processed=0
    try:
        while True:
            with Session(engine) as db:
                worked=process_one(db)
            if worked:processed+=1
            if not args.watch and (not worked or processed>=args.limit):break
            if not worked:time.sleep(1)
    except KeyboardInterrupt:pass
    finally:engine.dispose()
    print(json.dumps({'processed':processed,'worker':'analysis-only'}))


if __name__=='__main__':main()
