#!/usr/bin/env python3
"""Rebuild trace and audit archived results without GPU, SSD or elevated access."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import math

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / 'results/run-20260907-101847-hisparse'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_table(reference, generated):
    with reference.open() as f:
        expected = list(csv.DictReader(f))
    with generated.open() as f:
        actual = list(csv.DictReader(f))
    if len(expected) != len(actual):
        raise ValueError(f'Row count mismatch: {reference.name}')
    for i, (left, right) in enumerate(zip(expected, actual)):
        if left.keys() != right.keys():
            raise ValueError(f'Columns changed: {reference.name}')
        for key, value in left.items():
            if value == right[key]:
                continue
            try:
                a, b = float(value), float(right[key])
            except ValueError:
                raise ValueError(f'Text mismatch: {reference.name} row {i} {key}') from None
            if not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError(f'Numeric mismatch: {reference.name} row {i} {key}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    source = args.run_dir.resolve(strict=True)
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit(f'Refusing existing output directory: {output}')
    original = json.loads((source/'phase-audit.json').read_text())
    meta = json.loads((source/'workload.json').read_text())
    # Verify the audit's recorded inputs before recomputing a new audit.
    if original['status'] != 'verified':
        raise ValueError('Original audit is not verified')
    for name, digest in original['events'].items():
        if sha(source/name) != digest:
            raise ValueError(f'Archived event fingerprint changed: {name}')
    for phase, record in original['phases'].items():
        if sha(source/f'raw-{phase}.csv') != record['raw_sha256']:
            raise ValueError(f'Archived CSV fingerprint changed: {phase}')
        direct = record['direct_path']
        # Original paths are machine-specific. Resolve only the recorded log basename
        # within the known layout, never execute or read an archived absolute path.
        log = source/'logs'/phase/Path(direct['evidence']).name if phase.startswith('A') else source/f'logs/{phase}.log'
        if sha(log) != direct['sha256']:
            raise ValueError(f'Archived log fingerprint changed: {phase}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hisparse-review-', dir=output.parent) as tmp:
        tmp = Path(tmp)
        generated = tmp/'generated'
        subprocess.run([sys.executable, str(ROOT/'src/prepare_profile_trace.py'),
                        '--profile', str(source/'profile.json'),
                        '--source-workload', str(source/'workload.json'),
                        '--rounds', str(meta['rounds_per_configuration']),
                        '--warmups', str(meta['warmups']), '--run-dir', str(generated)], check=True,
                       stdout=subprocess.DEVNULL)
        if sha(generated/'trace.bin') != meta['trace_sha256']:
            raise ValueError('Regenerated trace hash differs from archived trace')
        work = tmp/'audit'
        work.mkdir()
        for name in ('workload.json', 'profile.json', 'operations.json'):
            shutil.copyfile(source/name, work/name)
        for phase in ('A1', 'B1', 'B2', 'A2'):
            shutil.copyfile(source/f'raw-{phase}.csv', work/f'raw-{phase}.csv')
        shutil.copytree(source/'logs', work/'logs')
        (generated/'trace.bin').replace(work/'trace.bin')
        subprocess.run([sys.executable, str(ROOT/'src/audit_abba.py'), '--run-dir', str(work)], check=True)
        with (tmp/'analysis.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT/'src/analyze_abba.py'), '--run-dir', str(work)],
                           check=True, stdout=log)
        for name in ('comparison.csv', 'phase-summary.csv'):
            compare_table(source/'analysis'/name, work/'analysis'/name)
        # Publish a compact review artifact; all input records and their hashes remain
        # in the archive. Generated manifests originally refer to temporary work paths.
        output.mkdir()
        shutil.copytree(work/'analysis', output/'analysis')
        shutil.copyfile(work/'phase-audit.json', output/'phase-audit.json')
        shutil.copyfile(tmp/'analysis.log', output/'analysis.log')
        (output/'verification.json').write_text(json.dumps(dict(
            status='pass', source_archive=str(source), trace_sha256=meta['trace_sha256'],
            measured_rows=4*len(meta['configurations'])*meta['rounds_per_configuration'],
            regenerated_trace_matches=True, csv_tables_match=True, gpu_workload_started=False,
            numeric_tolerance=dict(relative=1e-10, absolute=1e-10),
            note='Temporary input paths in regenerated manifests are historical review paths; source_archive holds retained inputs.'
        ), indent=2)+'\n')
    print(f'PASS: trace, archived evidence and both statistical tables verified. Output: {output}')


if __name__ == '__main__':
    main()
