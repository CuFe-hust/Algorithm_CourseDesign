"""Trusted start gate for local execution.

The supervisor starts this launcher instead of the student program. The launcher
creates its own session, stops itself and only then is the real program exec'ed
after the supervisor has registered the execution and re-verified ownership.
If the gate is never opened the launcher is killed while still stopped, so no
student code runs.
"""
import os
import signal
import sys


def main() -> None:
    if '--' not in sys.argv:
        raise SystemExit(2)
    command = sys.argv[sys.argv.index('--') + 1:]
    if not command:
        raise SystemExit(2)
    os.setsid()
    os.kill(os.getpid(), signal.SIGSTOP)
    try:
        os.execvp(command[0], command)
    except OSError:
        os._exit(127)


if __name__ == '__main__':
    main()
