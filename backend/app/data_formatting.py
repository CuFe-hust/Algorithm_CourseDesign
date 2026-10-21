"""Loss-aware, dependency-free conversion of the locally supplied course sources."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import xml.etree.ElementTree as ET
from zipfile import ZipFile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
NS = {'w': W, 'm': M}
QUESTION_FIELDS = ('code', 'type', 'title', 'difficulty', 'tags', 'statement', 'requirements', 'input', 'output', 'constraints', 'examples', 'source', 'references', 'tests', 'reference_solutions', 'rubric')


def _base(code, kind, title):
    return dict(code=code, type=kind, title=title, difficulty=1, tags=[], statement='', requirements='', input='', output='', constraints='', examples=[], source='', references=[], tests=[], reference_solutions=[], rubric=[])


def _section(text, heading):
    match = re.search(r'^## ' + re.escape(heading) + r'\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return match.group(1).strip() if match else ''


def _fences(text):
    return re.findall(r'^```([^\n]*)\n(.*?)^```\s*$', text, re.M | re.S)


def parse_programming(source_dir: Path) -> list[dict]:
    result = []
    for path in sorted(Path(source_dir).rglob('P*.md')):
        if '__MACOSX' in path.parts or path.name.startswith('._'):
            continue
        raw = path.read_text(encoding='utf-8-sig')
        title = re.search(r'^#\s+(P\d+)\s+(.+)', raw, re.M)
        if not title:
            continue
        q = _base('CODE-' + title[1], 'PROGRAMMING', title[2].strip())
        q['difficulty'] = re.search(r'难度[^\n]*', raw)[0].count('★')
        tags = re.search(r'标签[^\n]*', raw)[0]
        q['tags'] = re.findall(r'#([^\s#]+)', tags)
        q['source'] = re.search(r'来源\*\*[:：]\s*(.+)', raw)[1].strip()
        for field, heading in [('statement', '题目描述'), ('input', '输入格式'), ('output', '输出格式'), ('constraints', '数据范围')]:
            q[field] = _section(raw, heading)
        q['examples'] = [{'input': c[1], 'output': o[1]} for c, o in zip(_fences(_section(raw, '样例输入')), _fences(_section(raw, '样例输出')))]
        tests = _fences(_section(raw, '测试样例'))
        if len(tests) != 10:
            raise ValueError('Expected five source tests: ' + q['code'])
        q['tests'] = [dict(input=tests[i][1], output=tests[i + 1][1], public=False, weight=20) for i in range(0, 10, 2)]
        q['reference_solutions'] = [dict(language={'c': 'C', 'cpp': 'C++', 'python': 'Python'}.get(lang.strip().lower(), lang.strip()), content=code) for lang, code in _fences(_section(raw, '标准实现'))]
        q['source_file'] = 'data/source/programming/' + path.relative_to(source_dir).as_posix()
        q['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        q['verification'] = {'tests': 'source-provided; not independently verified', 'resource_limits': 'not specified by source'}
        result.append(q)
    return sorted(result, key=lambda q: q['code'])


def omml_to_latex(node: ET.Element) -> str:
    tag = node.tag.rsplit('}', 1)[-1]
    if tag == 't':
        return node.text or ''
    if tag in ('rPr', 'sty'):
        return ''
    if tag in ('sSub', 'sSup'):
        base = node.find('m:e', NS)
        script = node.find('m:sub' if tag == 'sSub' else 'm:sup', NS)
        return omml_to_latex(base) + ('_{' if tag == 'sSub' else '^{') + omml_to_latex(script) + '}'
    if tag not in ('oMath', 'oMathPara', 'r', 'e', 'sub', 'sup'):
        raise ValueError('Unsupported source OMML tag: ' + tag)
    return ''.join(omml_to_latex(child) for child in node)


def _paragraph(node):
    def walk(element):
        if element.tag == '{' + M + '}oMath':
            return '$' + omml_to_latex(element) + '$'
        if element.tag == '{' + W + '}t':
            return element.text or ''
        if element.tag == '{' + W + '}br':
            return '\n'
        if element.tag == '{' + W + '}tab':
            return '\t'
        return ''.join(walk(c) for c in element)
    return walk(node)


def parse_subjective(source_path: Path) -> list[dict]:
    with ZipFile(source_path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        relationships = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
    links = {n.attrib['Id']: n.attrib['Target'] for n in relationships if n.attrib.get('TargetMode') == 'External'}
    paragraphs = [p for p in root.find('w:body', NS) if p.tag == '{' + W + '}p']
    reference_catalog = {}
    active_reference = None
    bibliography = False
    for p in paragraphs:
        text = _paragraph(p).strip()
        if text.startswith('参考来源与延伸阅读'):
            bibliography = True
        if bibliography:
            ref = re.match(r'^(R\d{2})\s+(.+)', text)
            if ref:
                active_reference = ref[1]
                reference_catalog[active_reference] = {'id': ref[1], 'title': ref[2], 'urls': []}
            if active_reference:
                for link in p.findall('.//w:hyperlink', NS):
                    target = links.get(link.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'))
                    if target and target not in reference_catalog[active_reference]['urls']:
                        reference_catalog[active_reference]['urls'].append(target)
    result = []
    current = None
    blocks = []
    def finish():
        if current is None:
            return
        section = None
        statement, answer, solutions = [], [], []
        for text, code_style in blocks:
            if text.startswith('题型 '):
                current['metadata'] = {'difficulty_label': re.search(r'难度\s+(\S+)', text)[1], 'max_score': int(re.search(r'满分\s+(\d+)', text)[1]), 'suggested_minutes': int(re.search(r'建议\s+(\d+)', text)[1])}
                current['difficulty'] = {'基础': 1, '中等': 3, '进阶': 4, '挑战': 5}.get(current['metadata']['difficulty_label'], 3)
            elif text.startswith('知识点 '):
                current['tags'] = re.split(r'\s{2,}', text.removeprefix('知识点').strip())
            elif text == '题干':
                section = 'statement'
            elif text == '参考答案':
                section = 'answer'
            elif text.startswith('评分要点'):
                current['rubric'] = [dict(name=m[1].strip(' ；。'), max_score=int(m[2]), description=m[1].strip(' ；。')) for m in re.finditer(r'([^；]+?)\s+(\d+)\s*分', text.removeprefix('评分要点').strip())]
                section = None
            elif text.startswith('参考与延伸阅读'):
                current['references'] = [reference_catalog.get(r, {'id': r}) for r in re.findall(r'R\d{2}', text)]
                section = None
            elif text and section:
                rendered = '```python\n' + text + '\n```' if code_style else text
                (statement if section == 'statement' else answer).append(rendered)
                if code_style and section == 'answer':
                    solutions.append({'language': 'Python', 'content': text})
        current['statement'] = '\n\n'.join(statement)
        current['reference_answer'] = '\n\n'.join(answer)
        current['reference_solutions'] = solutions
        result.append(current)
    for p in paragraphs:
        text = _paragraph(p).strip('\r\n')
        if text.startswith('参考来源与延伸阅读'):
            finish()
            current = None
            break
        title = re.match(r'^([APO]\d{2})\s+(.+)', text)
        if title:
            finish()
            code = title[1]
            current = _base('SUB-' + code, {'A': 'ALGORITHM_ANALYSIS', 'P': 'PROOF', 'O': 'OPEN_QUESTION'}[code[0]], title[2].strip())
            current.update(source='算法设计与分析课程主观题库（教师参考版）', source_file='data/source/subjective-50.docx', source_anchor=code, source_math_omml=[])
            blocks = []
        elif current is not None:
            style = p.find('w:pPr/w:pStyle', NS)
            blocks.append((text, style is not None and style.attrib.get('{' + W + '}val') == 'Code'))
            current['source_math_omml'].extend(ET.tostring(m, encoding='unicode') for m in p.findall('.//m:oMath', NS))
    return result


def read_roster_xlsx(path: Path) -> list[dict]:
    """Read identity fields only in memory, without exposing them in diagnostics."""
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(s.itertext()) for s in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        sheets = sorted(n for n in archive.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n))
        records = []
        for name in sheets:
            header = None
            for row in ET.fromstring(archive.read(name)).findall('.//x:sheetData/x:row', ns):
                values = {}
                for cell in row.findall('x:c', ns):
                    col = re.match('[A-Z]+', cell.attrib['r'])[0]
                    value = cell.find('x:v', ns)
                    value = value.text if value is not None else ''.join(cell.find('x:is', ns).itertext()) if cell.find('x:is', ns) is not None else ''
                    values[col] = shared[int(value)] if cell.attrib.get('t') == 's' and value else value
                if header is None:
                    found = {}
                    for col, value in values.items():
                        if value.strip() in ('学号', '姓名', '班级', '班级名称', '行政班级'):
                            found[{'学号': 'student_no', '姓名': 'full_name'}.get(value.strip(), 'class_name')] = col
                    if len(found) == 3:
                        header = found
                elif all(values.get(col, '').strip() for col in header.values()):
                    records.append({field: values[col].strip() for field, col in header.items()})
    if not records or len({r['student_no'] for r in records}) != len(records):
        raise ValueError('Roster missing or duplicate student identifiers')
    return records


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Explicit bytes avoid Windows newline translation and keep manifest hashes portable.
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def anonymize_roster(records: list[dict], private_dir: Path) -> tuple[dict, dict]:
    """Persist private salt/registry; public identifiers remain stable across reorderings."""
    private_dir.mkdir(parents=True, exist_ok=True)
    registry_path = private_dir / 'registry.json'
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding='utf-8'))
    else:
        registry = {'salt': secrets.token_hex(32), 'students': {}, 'classes': {}}
    def digest(value):
        return hmac.new(bytes.fromhex(registry['salt']), value.encode('utf-8'), hashlib.sha256).hexdigest()
    classes = registry['classes']
    for name in sorted({r['class_name'] for r in records}, key=digest):
        key = digest('class:' + name)
        if key not in classes:
            classes[key] = 'CLASS-' + str(len(classes) + 1).zfill(2)
    students = registry['students']
    for r in sorted(records, key=lambda r: digest('student:' + r['student_no'])):
        key = digest('student:' + r['student_no'])
        if key not in students:
            students[key] = len(students) + 1
    public = dict(schema_version=1, privacy='anonymized', classes=[], students=[])
    private = dict(schema_version=1, privacy='real-local-only', classes=[], students=[])
    for name in sorted({r['class_name'] for r in records}, key=lambda name: classes[digest('class:' + name)]):
        code = classes[digest('class:' + name)]
        public['classes'].append(dict(class_code=code, name='教学班' + code[-2:]))
        private['classes'].append(dict(class_code=code, name=name))
    for r in sorted(records, key=lambda r: students[digest('student:' + r['student_no'])]):
        key = digest('student:' + r['student_no'])
        number = str(students[key]).zfill(4)
        common = dict(record_key='student-' + number, login_name='dataset.student' + number, class_code=classes[digest('class:' + r['class_name'])])
        public['students'].append(dict(common, student_no='ANON2026' + number, full_name='学习者' + number))
        private['students'].append(dict(common, student_no=r['student_no'], full_name=r['full_name']))
    write_json(registry_path, registry)
    write_json(private_dir / 'students.real.json', private)
    return public, private


def validate_datasets(programming, subjective, students):
    checks = dict(programming_count=len(programming) == 70, subjective_count=len(subjective) == 50,
                  tests_count=sum(len(q['tests']) for q in programming) == 350,
                  reference_implementations=sum(len(q['reference_solutions']) for q in programming) == 210,
                  formulas_preserved=sum(len(q['source_math_omml']) for q in subjective) == 49,
                  rubric_totals=all(sum(r['max_score'] for r in q['rubric']) == 100 for q in subjective),
                  student_count=len(students['students']) == 217, class_count=len(students['classes']) == 8,
                  unique_student_identifiers=all(len({s[k] for s in students['students']}) == len(students['students']) for k in ('record_key', 'login_name', 'student_no')))
    if not all(checks.values()):
        raise ValueError('Dataset checks failed: ' + ', '.join(k for k, passed in checks.items() if not passed))
    return checks
