"""Generate portable GitHub Issue templates from docs/issues (no network calls)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = [
    ('01-teacher.md', '教师模块', '教师页面、名单、题库、作业与管理入口'),
    ('02-student.md', '学生模块', '学生作答、历史、匿名互评与反馈'),
    ('03-database-analysis.md', '分析模块', '共享数据库上的分析流程、算法与结果服务'),
]


def main():
    target = ROOT / '.github/ISSUE_TEMPLATE'
    target.mkdir(parents=True, exist_ok=True)
    for filename, name, about in TEMPLATES:
        source = ROOT / 'docs/issues' / filename
        body = source.read_text(encoding='utf-8')
        title = body.splitlines()[0].removeprefix('# ')

        def portable_link(match):
            path = match.group(2)
            if '://' in path or path.startswith('#'):
                return match.group(0)
            destination = (source.parent / path).resolve()
            return '`' + destination.relative_to(ROOT).as_posix() + '`'

        body = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', portable_link, body)
        header = f'---\nname: "{name}"\nabout: "{about}"\ntitle: "{title}"\nlabels: ""\nassignees: ""\n---\n\n'
        (target / filename).write_text(header + body, encoding='utf-8', newline='\n')
    print('Generated 3 GitHub Issue templates from docs/issues; no online Issue was created.')


if __name__ == '__main__':
    main()
