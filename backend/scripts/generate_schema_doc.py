"""Regenerate docs/design/shared/database-schema.md from the SQLAlchemy models.

Run from the backend directory so the application package is importable:
    ../.venv/bin/python -m scripts.generate_schema_doc
"""
from pathlib import Path

from sqlalchemy.dialects import postgresql

from app.db.base import Base
from app.db import models  # noqa: F401 - registers every table

TARGET = Path(__file__).resolve().parents[2] / 'docs/design/shared/database-schema.md'
HEADER = """# 当前数据库字段

实现版本：PostgreSQL迁移{head}；{count}张业务表，另有alembic_version。由SQLAlchemy模型自动生成类型与外键。

时间戳均带时区，服务端按UTC输出；ID为有符号64位整数，API以字符串传输。JSON列使用JSONB。
"""


def column_type(column) -> str:
    return str(column.type.compile(dialect=postgresql.dialect()))


def foreign_key(column) -> str:
    for key in column.foreign_keys:
        return f'{key.column.table.name}.{key.column.name}'
    return '—'


def render() -> str:
    dialect = postgresql.dialect()
    tables = sorted(Base.metadata.tables.values(), key=lambda table: table.name)
    head = 'pg0003'
    lines = [HEADER.format(head=head, count=len(tables))]
    for table in tables:
        lines.append(f'## {table.name}\n')
        lines.append('| 字段 | PostgreSQL类型 | 可空 | 外键 |')
        lines.append('|---|---|---|---|')
        for column in table.columns:
            nullable = '否' if not column.nullable else '是'
            lines.append(f'| {column.name} | {column_type(column)} | {nullable} | {foreign_key(column)} |')
        lines.append('')
    del dialect
    return '\n'.join(lines).rstrip() + '\n'


def main() -> None:
    TARGET.write_text(render(), encoding='utf-8')
    print(f'wrote {TARGET}')


if __name__ == '__main__':
    main()
