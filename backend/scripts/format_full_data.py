"""Export course source snapshots; real roster output is strictly outside the repository."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from app.data_formatting import (anonymize_roster, parse_programming, parse_subjective,
                                 read_roster_xlsx, validate_datasets, write_json)

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster-source', type=Path, default=ROOT.parent / '2026.10.21 数据库形态与搭建/题目/2024级全日制普通本科生数据.xlsx')
    args = parser.parse_args()
    programming = parse_programming(ROOT / 'data/source/programming')
    subjective = parse_subjective(ROOT / 'data/source/subjective-50.docx')
    private_dir = Path(os.environ['LOCALAPPDATA']) / 'AlgorithmReview/private-data'
    students, _ = anonymize_roster(read_roster_xlsx(args.roster_source), private_dir)
    checks = validate_datasets(programming, subjective, students)
    output = ROOT / 'data/formatted'
    for name, payload in [('questions.programming.json', programming), ('questions.subjective.json', subjective), ('students.anonymized.json', students)]:
        write_json(output / name, payload)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob('*.json')) if p.name != 'manifest.json'}
    manifest = dict(schema_version=1, data_version='2026-10-21.1',
                    counts=dict(questions=120, programming=70, subjective=50, analysis=20, proof=20, open=10, tests=350, programming_reference_solutions=210, formulas=49, students=217, classes=8),
                    sha256=hashes, validation=checks,
                    source_validation='Structure checked; source-provided algorithm implementations and test outputs have not been independently executed.')
    write_json(output / 'manifest.json', manifest)
    print(json.dumps({'counts': manifest['counts'], 'validation_passed': all(checks.values())}))


if __name__ == '__main__':
    main()
