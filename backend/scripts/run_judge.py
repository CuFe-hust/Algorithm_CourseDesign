"""Single-node judge runner for LOCAL (or MOCK) execution.

Usage:
    python -m scripts.run_judge --once                # claim and run one batch, then exit
    python -m scripts.run_judge --loop                # hold the node dispatch lock and keep running
    python -m scripts.run_judge --recover             # clean up expired leases now
    python -m scripts.run_judge --purge-aux           # bounded auxiliary-data cleanup
    python -m scripts.run_judge --mode LOCAL --concurrency 2 --loop

Only one process may hold the node dispatch lock; a second `--loop` start exits
with a non-zero status instead of silently running a second scheduler.
"""
import argparse
import json
import signal
import sys
import threading

from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.judge import config, maintenance, recovery
from app.judge.scheduler import Scheduler


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='单节点评测执行器')
    parser.add_argument('--mode', choices=config.EXECUTION_MODES, default=config.execution_mode())
    parser.add_argument('--concurrency', type=int, default=None)
    parser.add_argument('--once', action='store_true', help='运行一批后退出')
    parser.add_argument('--loop', action='store_true', help='持续运行直到收到 SIGINT/SIGTERM')
    parser.add_argument('--recover', action='store_true', help='清理租约过期的任务')
    parser.add_argument('--purge-aux', action='store_true', help='清理过期会话、限流桶和诊断')
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if not any([args.once, args.loop, args.recover, args.purge_aux]):
        _parser().error('至少指定 --once、--loop、--recover 或 --purge-aux 之一')
    if (args.once or args.loop) and not config.driver_available(args.mode):
        print(json.dumps({'error': f'执行模式 {args.mode} 尚未实现'}), file=sys.stderr)
        return 2
    engine = make_engine()
    try:
        if args.recover:
            print(json.dumps({'recovered': recovery.recover_expired(engine)}), flush=True)
        if args.purge_aux:
            print(json.dumps({'purged': maintenance.purge_all(engine)}, ensure_ascii=False), flush=True)
        if args.once:
            scheduler = Scheduler(engine, mode=args.mode, concurrency=args.concurrency)
            print(json.dumps({'mode': scheduler.mode, 'started': scheduler.run_once()}), flush=True)
        if args.loop:
            scheduler = Scheduler(engine, mode=args.mode, concurrency=args.concurrency)
            stop = threading.Event()

            def handle(signum, frame):  # noqa: ARG001 - signal handler signature
                stop.set()

            signal.signal(signal.SIGINT, handle)
            signal.signal(signal.SIGTERM, handle)
            if not scheduler.acquire_main():
                print(json.dumps({'error': 'dispatch lock busy; another scheduler is running'}), file=sys.stderr)
                return 2
            print(json.dumps({'mode': scheduler.mode, 'concurrency': scheduler.concurrency,
                              'status': 'running'}), flush=True)
            try:
                while not stop.is_set():
                    if not scheduler.healthy:
                        print(json.dumps({'error': 'dispatch connection lost'}), file=sys.stderr)
                        return 3
                    if scheduler.run_once() == 0:
                        stop.wait(1.0)
            finally:
                scheduler.release_main()
            print(json.dumps({'status': 'stopped'}), flush=True)
        return 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
