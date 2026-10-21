"""Source conversion tests; roster fixtures are entirely synthetic."""
import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from app import data_formatting as fmt

ROOT = Path(__file__).resolve().parents[2]


class FormattingTests(unittest.TestCase):
    def test_json_bytes_are_utf8_lf_and_manifest_hashes_match(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'snapshot.json'
            fmt.write_json(output, {'title': '跨平台快照', 'rows': [1, 2]})
            content = output.read_bytes()
            self.assertNotIn(b'\r\n', content)
            self.assertEqual(content, (json.dumps({'title': '跨平台快照', 'rows': [1, 2]}, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        output = ROOT / 'data/formatted'
        manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected_hash in manifest['sha256'].items():
            content = (output / name).read_bytes()
            self.assertNotIn(b'\r\n', content)
            self.assertEqual(hashlib.sha256(content).hexdigest(), expected_hash)

    def test_full_question_sources(self):
        programming = fmt.parse_programming(ROOT / 'data/source/programming')
        subjective = fmt.parse_subjective(ROOT / 'data/source/subjective-50.docx')
        self.assertEqual(len(programming), 70)
        self.assertEqual(sum(len(q['tests']) for q in programming), 350)
        self.assertEqual(sum(len(q['reference_solutions']) for q in programming), 210)
        self.assertEqual(len(subjective), 50)
        self.assertEqual({q['type'] for q in subjective}, {'ALGORITHM_ANALYSIS', 'PROOF', 'OPEN_QUESTION'})
        for prefix, count in [('A', 20), ('P', 20), ('O', 10)]:
            self.assertEqual(sum(q['code'].startswith('SUB-' + prefix) for q in subjective), count)
        self.assertEqual(sum(len(q['source_math_omml']) for q in subjective), 49)
        self.assertIn('_{n}', subjective[0]['reference_answer'])
        self.assertIn('\n    count = 0\n', subjective[0]['statement'])
        for q in subjective:
            self.assertEqual(sum(r['max_score'] for r in q['rubric']), 100)
        for q in programming + subjective:
            self.assertTrue(1 <= q['difficulty'] <= 5)
            self.assertTrue(set(fmt.QUESTION_FIELDS).issubset(q))
        self.assertEqual(len({q['code'] for q in programming + subjective}), 120)
        for q in programming:
            self.assertEqual({s['language'] for s in q['reference_solutions']}, {'C', 'C++', 'Python'})
            for field in ('input', 'output', 'constraints', 'statement', 'examples'):
                self.assertTrue(q[field])
        for q in subjective:
            self.assertTrue(q['reference_answer'])
            self.assertTrue(q['references'])
            for solution in q['reference_solutions']:
                compile(solution['content'], q['code'], 'exec')

    def test_math_superscripts_and_subscripts(self):
        node = ET.fromstring('<m:oMath xmlns:m="' + fmt.M + '"><m:sSup><m:e><m:sSub><m:e><m:r><m:t>a</m:t></m:r></m:e><m:sub><m:r><m:t>i</m:t></m:r></m:sub></m:sSub></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:oMath>')
        self.assertEqual(fmt.omml_to_latex(node), 'a_{i}^{2}')

    def test_xlsx_shared_strings_and_string_student_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'synthetic.xlsx'
            ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
            with ZipFile(source, 'w') as archive:
                archive.writestr('xl/sharedStrings.xml', '<sst xmlns="' + ns + '">' + ''.join('<si><t>' + s + '</t></si>' for s in ['学号', '姓名', '班级', '000012', '虚构甲', '虚构班']) + '</sst>')
                archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="' + ns + '"><sheetData><row>' + ''.join('<c r="' + col + '1" t="s"><v>' + str(i) + '</v></c>' for i, col in enumerate('ABC')) + '</row><row>' + ''.join('<c r="' + col + '2" t="s"><v>' + str(i + 3) + '</v></c>' for i, col in enumerate('ABC')) + '</row></sheetData></worksheet>')
            rows = fmt.read_roster_xlsx(source)
            self.assertEqual(rows, [{'student_no': '000012', 'full_name': '虚构甲', 'class_name': '虚构班'}])

    def test_anonymization_preserves_structure_and_is_stable(self):
        roster = [{'student_no': str(i), 'full_name': '假名' + str(i), 'class_name': '虚构班' + str(i % 2)} for i in range(8)]
        with tempfile.TemporaryDirectory() as folder:
            public, private = fmt.anonymize_roster(roster, Path(folder))
            again, _ = fmt.anonymize_roster(list(reversed(roster)), Path(folder))
            self.assertEqual(public, again)
            self.assertEqual(len(public['classes']), 2)
            self.assertEqual(len({s['student_no'] for s in public['students']}), 8)
            self.assertEqual(len({s['record_key'] for s in public['students']}), 8)
            self.assertNotIn('假名', str(public))
            self.assertNotIn('虚构班', str(public))
            for real, anon in zip(private['students'], public['students']):
                for key in ['record_key', 'login_name', 'class_code']:
                    self.assertEqual(real[key], anon[key])
            self.assertEqual(sorted(sum(s['class_code'] == c['class_code'] for s in public['students']) for c in public['classes']), [4, 4])


if __name__ == '__main__':
    unittest.main()
