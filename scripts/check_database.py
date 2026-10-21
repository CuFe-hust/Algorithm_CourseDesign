"""Validate project PostgreSQL role and Unicode DDL/DML in the test database only."""
import json
import uuid
from pathlib import Path
import psycopg
from psycopg import sql
from dotenv import dotenv_values


def main():
    values = dotenv_values(Path(__file__).resolve().parents[1] / '.env')
    if values.get('DB_TEST_NAME') != 'algorithm_review_test':
        raise RuntimeError('Refusing checks outside the dedicated test database.')
    options = dict(host=values['DB_HOST'], port=int(values['DB_PORT']), user=values['DB_USER'],
                   password=values['DB_PASSWORD'], connect_timeout=5)
    counts = {}
    for database in (values['DB_NAME'], values['DB_TEST_NAME']):
        with psycopg.connect(**options, dbname=database) as connection:
            role = connection.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone()
            assert role == (False, False, False)
            counts[database] = connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
    table = sql.Identifier('__connection_check_' + uuid.uuid4().hex)
    with psycopg.connect(**options, dbname=values['DB_TEST_NAME']) as connection:
        connection.execute(sql.SQL('CREATE TABLE {} (id bigint PRIMARY KEY, content text NOT NULL)').format(table))
        connection.execute(sql.SQL('INSERT INTO {} VALUES (1, %s)').format(table), ('连接验证✓',))
        assert connection.execute(sql.SQL('SELECT content FROM {}').format(table)).fetchone()[0] == '连接验证✓'
        connection.rollback()  # PostgreSQL DDL is transactional: leave no temporary table.
        try:
            connection.execute('SELECT rolpassword FROM pg_authid')
        except psycopg.errors.InsufficientPrivilege:
            connection.rollback()
        else:
            raise RuntimeError('Unexpected admin table access.')
    print(json.dumps(dict(status='PASS', engine='PostgreSQL', ddl_dml_unicode=True,
                         admin_tables_denied=True, table_counts=counts, credentials_printed=False)))


if __name__ == '__main__':
    main()
