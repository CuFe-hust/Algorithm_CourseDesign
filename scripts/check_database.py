"""Verify project credentials and DDL/DML in the dedicated validation database."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import uuid

from setup_local_mysql import PROJECT, STATE, binaries


def main() -> None:
    env = dict(line.split('=', 1) for line in (PROJECT / '.env').read_text(encoding='utf-8').splitlines()
               if line.strip() and not line.lstrip().startswith('#'))
    if env['DB_TEST_NAME'] != 'algorithm_review_test':
        raise RuntimeError('Refusing a write check outside the dedicated validation database.')
    _, client = binaries()
    STATE.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='app-check-', suffix='.ini', dir=STATE)
    table = '__connection_check_' + uuid.uuid4().hex
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            file.write('[client]\n' + '\n'.join([
                'host=' + env['DB_HOST'], 'port=' + env['DB_PORT'], 'user=' + env['DB_USER'],
                'password=' + env['DB_PASSWORD'], 'protocol=tcp', '',
            ]))

        def run(sql: str, expect_success: bool = True) -> str:
            result = subprocess.run(
                [str(client), f'--defaults-file={name}', '--connect-timeout=3', '--batch',
                 '--skip-column-names', '--default-character-set=utf8mb4'],
                input=sql, capture_output=True, encoding='utf-8', timeout=15,
            )
            if (result.returncode == 0) != expect_success:
                raise RuntimeError('Database verification failed; credentials omitted.')
            return result.stdout.strip()

        identity = run('SELECT CURRENT_USER();')
        if not identity.startswith('algorithm_review_app@'):
            raise RuntimeError('Verification must use the project account.')
        grants = run('SHOW GRANTS;')
        for grant in grants.splitlines():
            if 'GRANT OPTION' in grant or (' ON *.* ' in grant and not grant.startswith('GRANT USAGE ')):
                raise RuntimeError('Unexpected global/admin privileges.')
        run('SELECT COUNT(*) FROM mysql.user;', expect_success=False)
        for database in [env['DB_NAME'], env['DB_TEST_NAME']]:
            run(f'USE `{database}`; SELECT DATABASE();')
        try:
            result = run(f"""USE algorithm_review_test;
CREATE TABLE `{table}` (id BIGINT UNSIGNED PRIMARY KEY, content VARCHAR(100) NOT NULL) CHARACTER SET utf8mb4;
INSERT INTO `{table}` VALUES (1, '连接验证✓');
SELECT content FROM `{table}` WHERE id=1;
""")
            if result != '连接验证✓':
                raise RuntimeError('Unicode round trip failed.')
        finally:
            run(f'USE algorithm_review_test; DROP TABLE IF EXISTS `{table}`;')
        counts = {}
        for database in [env['DB_NAME'], env['DB_TEST_NAME']]:
            counts[database] = int(run(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{database}';"))
        print(json.dumps({'status': 'PASS', 'account': identity, 'ddl_dml_unicode': True,
                          'admin_tables_denied': True, 'table_counts_after_cleanup': counts,
                          'credentials_printed': False}, ensure_ascii=True))
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
