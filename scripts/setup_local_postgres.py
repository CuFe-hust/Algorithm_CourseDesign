"""Start an isolated local PostgreSQL instance without changing existing services.

Use the project's .venv Python (psycopg and python-dotenv required).
Install PostgreSQL binaries first or set PG_BIN. Credentials are never printed.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import psycopg
from psycopg import sql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'AlgorithmReview'
STATE = LOCAL / 'postgres-local'
DATA = STATE / 'data'
PORT = 5433
ADMIN = 'algorithm_review_admin'
APP = 'algorithm_review_app'
DATABASES = ['algorithm_review', 'algorithm_review_test']


def find_bin() -> Path:
    configured = os.getenv('PG_BIN')
    candidates = [Path(configured)] if configured else []
    candidates.append(LOCAL / 'runtimes/postgresql-18.6/pgsql/bin')
    installed = Path(os.getenv('ProgramFiles', 'C:/Program Files')) / 'PostgreSQL'
    if installed.exists(): candidates.extend(sorted(installed.glob('*/bin'), reverse=True))
    for folder in candidates:
        if all((folder / x).is_file() for x in ['pg_ctl.exe', 'initdb.exe', 'psql.exe']): return folder
    raise RuntimeError('PostgreSQL programs not found. Install the official binaries or set PG_BIN.')


def run(program: Path, *args):
    # On Windows a detached postgres child may inherit pipe handles and keep communicate()
    # waiting after pg_ctl exits. File-backed handles have no pipe EOF dependency.
    with (STATE/'commands.log').open('ab') as log:
        result = subprocess.run([str(program), *map(str, args)], stdout=log, stderr=log,
                                timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f'{program.name} failed; inspect the dedicated commands.log and server.log.')


def admin_connection(state):
    return psycopg.connect(host='127.0.0.1', port=PORT, user=ADMIN, password=state['admin_password'],
                           dbname='postgres', connect_timeout=5, autocommit=True)


def assert_instance(connection):
    actual = connection.execute('SHOW data_directory').fetchone()[0]
    if Path(actual).resolve() != DATA.resolve(): raise RuntimeError('Unexpected instance; refusing to change it.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    folder = find_bin()
    state_file = STATE / 'admin.json'
    env_path = ROOT / '.env'
    if args.stop:
        if not state_file.exists(): raise RuntimeError('No dedicated instance state; refusing to stop another service.')
        state = json.loads(state_file.read_text(encoding='utf-8'))
        with admin_connection(state) as connection: assert_instance(connection)
        run(folder/'pg_ctl.exe', '-D', DATA, '-m', 'fast', '-w', 'stop')
        print('Stopped the project PostgreSQL instance only.')
        return
    existing = dotenv_values(env_path) if env_path.exists() else {}
    if not state_file.exists():
        with socket.socket() as sock:
            if DATA.exists() or sock.connect_ex(('127.0.0.1', PORT)) == 0:
                raise RuntimeError('Existing data/port without project state; refusing to overwrite.')
        STATE.mkdir(parents=True, exist_ok=True)
        state = {'admin_password': secrets.token_hex(24), 'app_password': secrets.token_hex(24),
                 'app_secret': existing.get('APP_SECRET') or secrets.token_hex(32), 'configured': False}
        state_file.write_text(json.dumps(state), encoding='utf-8')
    else: state = json.loads(state_file.read_text(encoding='utf-8'))
    if not (DATA/'PG_VERSION').exists():
        fd, name = tempfile.mkstemp(prefix='pg-init-', suffix='.txt', dir=STATE)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file: file.write(state['admin_password']+'\n')
            run(folder/'initdb.exe', '-D', DATA, '-U', ADMIN, '--encoding=UTF8', '--locale=C',
                '--auth-host=scram-sha-256', '--auth-local=scram-sha-256', f'--pwfile={name}')
        finally: Path(name).unlink(missing_ok=True)
    status = subprocess.run([str(folder/'pg_ctl.exe'), '-D', str(DATA), 'status'], capture_output=True)
    if status.returncode:
        run(folder/'pg_ctl.exe', '-D', DATA, '-l', STATE/'server.log', '-o', f'-p {PORT} -h 127.0.0.1', '-w', 'start')
    with admin_connection(state) as connection:
        assert_instance(connection)
        if not state['configured']:
            if not connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (APP,)).fetchone():
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
                    sql.Identifier(APP), sql.Literal(state['app_password'])))
            else:
                connection.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
                    sql.Identifier(APP), sql.Literal(state['app_password'])))
            for database in DATABASES:
                if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (database,)).fetchone():
                    connection.execute(sql.SQL('CREATE DATABASE {} OWNER {} ENCODING {} TEMPLATE template0').format(
                        sql.Identifier(database), sql.Identifier(APP), sql.Literal('UTF8')))
                connection.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(database)))
            state['configured'] = True
            state_file.write_text(json.dumps(state), encoding='utf-8')
        version = connection.execute('SHOW server_version').fetchone()[0]
    generated = {'DB_ENGINE':'postgresql','DB_HOST':'127.0.0.1','DB_PORT':str(PORT), 'DB_NAME':DATABASES[0],
                 'DB_TEST_NAME':DATABASES[1], 'DB_USER':APP, 'DB_PASSWORD':state['app_password'], 'APP_SECRET':state['app_secret']}
    if existing.get('DB_ENGINE')=='postgresql':
        if any(existing.get(k)!=v for k,v in generated.items()):
            raise RuntimeError('Existing PostgreSQL .env differs; refusing to overwrite local settings.')
    else:
        if env_path.exists():
            backup = STATE/'previous-mysql.env'
            if not backup.exists(): backup.write_bytes(env_path.read_bytes())
        values={**existing,**generated}
        env_path.write_text('\n'.join(k+'='+str(v) for k,v in values.items() if v is not None)+'\n',encoding='utf-8',newline='\n')
    with psycopg.connect(host='127.0.0.1',port=PORT,user=APP,password=state['app_password'],dbname=DATABASES[0],connect_timeout=5) as connection:
        role=connection.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone()
        assert role==(False,False,False)
    print(json.dumps({'status':'ready','database_engine':'PostgreSQL','server_version':version,'host':'127.0.0.1',
                      'port':PORT,'databases':DATABASES,'config_file':str(env_path),'credentials_printed':False},ensure_ascii=True))


if __name__=='__main__': main()
