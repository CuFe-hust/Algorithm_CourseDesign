"""Create/start an isolated Windows MySQL instance. Never reset system MySQL.

Secrets are stored in the local state folder and ignored project .env, not stdout.
This script requires existing MySQL server/client binaries, not administrator access.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'AlgorithmReview/mysql-local'
DATA = STATE / 'data'
PORT = 3307


def port_open() -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(('127.0.0.1', PORT)) == 0


def binaries() -> tuple[Path, Path]:
    configured = os.environ.get('MYSQL_BIN')
    candidates = [Path(configured)] if configured else []
    base = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'MySQL'
    if base.exists():
        candidates.extend(sorted(base.glob('MySQL Server */bin'), reverse=True))
    for folder in candidates:
        if (folder / 'mysqld.exe').is_file() and (folder / 'mysql.exe').is_file():
            return folder / 'mysqld.exe', folder / 'mysql.exe'
    raise RuntimeError('MySQL binaries not found. Set MYSQL_BIN to the existing MySQL bin folder.')


def query(client: Path, password: str, sql: str) -> str:
    config = f'[client]\nhost=127.0.0.1\nport={PORT}\nuser=root\npassword={password}\nprotocol=tcp\n'
    fd, name = tempfile.mkstemp(prefix='mysql-client-', suffix='.ini', dir=STATE)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(config)
        result = subprocess.run(
            [str(client), f'--defaults-file={name}', '--connect-timeout=3', '--batch', '--skip-column-names', '--default-character-set=utf8mb4'],
            input=sql, encoding='utf-8', capture_output=True, timeout=30,
        )
        if result.returncode:
            raise RuntimeError('MySQL request failed (credentials omitted). Check the dedicated instance log.')
        return result.stdout.strip()
    finally:
        Path(name).unlink(missing_ok=True)


def assert_instance(client: Path, password: str) -> None:
    actual = query(client, password, 'SELECT @@datadir;')
    if Path(actual).resolve() != DATA.resolve():
        raise RuntimeError('Port belongs to another instance. Refusing database/account changes.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true', help='Stop only the dedicated project instance.')
    args = parser.parse_args()
    server, client = binaries()
    state_file = STATE / 'admin.json'
    if args.stop:
        if not port_open():
            print('Dedicated instance is already stopped.')
            return
        if not state_file.exists():
            raise RuntimeError('No project state. Refusing to stop an unknown instance.')
        state = json.loads(state_file.read_text(encoding='utf-8'))
        assert_instance(client, state['root_password'])
        query(client, state['root_password'], 'SHUTDOWN;')
        print('Dedicated project instance stopped; system MySQL unchanged.')
        return

    if not state_file.exists():
        if port_open() or DATA.exists():
            raise RuntimeError('Existing port/data without project state. Refusing to initialize.')
        if shutil.disk_usage(Path.home()).free < 2 * 1024**3:
            raise RuntimeError('At least 2 GiB free space is required.')
        if (PROJECT / '.env').exists():
            raise RuntimeError('Existing .env found. Refusing to replace local configuration.')
        STATE.mkdir(parents=True, exist_ok=True)
        state = {'root_password': secrets.token_hex(24), 'app_password': secrets.token_hex(24),
                 'app_secret': secrets.token_hex(32), 'configured': False}
        state_file.write_text(json.dumps(state), encoding='utf-8')
    else:
        state = json.loads(state_file.read_text(encoding='utf-8'))

    if not DATA.exists():
        result = subprocess.run(
            [str(server), '--no-defaults', '--initialize-insecure', f'--basedir={server.parent.parent}', f'--datadir={DATA}', '--console'],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode:
            raise RuntimeError('Dedicated initialization failed: ' + result.stderr[-2000:])

    if not port_open():
        with (STATE / 'launcher.log').open('ab') as log:
            subprocess.Popen(
                [str(server), '--no-defaults', f'--basedir={server.parent.parent}', f'--datadir={DATA}',
                 f'--port={PORT}', '--bind-address=127.0.0.1', '--mysqlx=OFF',
                 '--character-set-server=utf8mb4', '--collation-server=utf8mb4_0900_ai_ci',
                 f'--log-error={STATE / "server.log"}', f'--pid-file={STATE / "server.pid"}'],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
        deadline = time.monotonic() + 45
        while not port_open() and time.monotonic() < deadline:
            time.sleep(0.25)
        if not port_open():
            raise RuntimeError('Dedicated instance did not start; inspect local server.log.')

    password = state['root_password']
    if not state['configured']:
        try:
            assert_instance(client, password)
        except RuntimeError:
            password = ''
            assert_instance(client, password)
        app_password = state['app_password']
        query(client, password, f"""
ALTER USER 'root'@'localhost' IDENTIFIED BY '{state['root_password']}';
CREATE DATABASE IF NOT EXISTS algorithm_review CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS algorithm_review_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'algorithm_review_app'@'127.0.0.1' IDENTIFIED BY '{app_password}';
ALTER USER 'algorithm_review_app'@'127.0.0.1' IDENTIFIED BY '{app_password}';
GRANT ALL PRIVILEGES ON algorithm_review.* TO 'algorithm_review_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON algorithm_review_test.* TO 'algorithm_review_app'@'127.0.0.1';
""")
        state['configured'] = True
        state_file.write_text(json.dumps(state), encoding='utf-8')

    assert_instance(client, state['root_password'])
    env = '\n'.join([
        'DB_HOST=127.0.0.1', f'DB_PORT={PORT}', 'DB_NAME=algorithm_review',
        'DB_TEST_NAME=algorithm_review_test', 'DB_USER=algorithm_review_app',
        'DB_PASSWORD=' + state['app_password'], 'APP_SECRET=' + state['app_secret'], '',
    ])
    env_file = PROJECT / '.env'
    if not env_file.exists():
        env_file.write_text(env, encoding='utf-8')
    else:
        actual = dict(line.split('=', 1) for line in env_file.read_text(encoding='utf-8').splitlines()
                      if line.strip() and not line.lstrip().startswith('#') and '=' in line)
        expected = dict(line.split('=', 1) for line in env.splitlines() if '=' in line)
        if any(actual.get(key) != value for key, value in expected.items()):
            raise RuntimeError('Existing .env differs from local instance state; configuration was not overwritten.')
    version = query(client, state['root_password'], 'SELECT VERSION();')
    print(json.dumps({'status': 'ready', 'host': '127.0.0.1', 'port': PORT, 'mysql_version': version,
                      'databases': ['algorithm_review', 'algorithm_review_test'],
                      'config_file': str(env_file), 'secrets_printed': False}, ensure_ascii=True))


if __name__ == '__main__':
    main()
