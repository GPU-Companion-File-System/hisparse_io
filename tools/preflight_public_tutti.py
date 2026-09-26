#!/usr/bin/env python3
"""Read-only snvme ABI check before any GPU workload or device handover."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=ROOT/'build/public-v011')
    parser.add_argument('--device', type=Path, required=True, help='Existing snvme character device to query; never a filesystem image')
    args = parser.parse_args()
    binary = args.build_dir/'bin/snvme_info'
    if not binary.is_file() or not args.device.is_char_device():
        parser.error('Build snvme_info first and specify an existing character device')
    result = subprocess.run([str(binary), str(args.device)], capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode:
        print(result.stderr.strip() or 'BLOCKED: installed kernel ABI does not match the pinned public release.')
        raise SystemExit(result.returncode)
    info = json.loads(result.stdout)
    if info['block_size'] != 4096:
        raise SystemExit('BLOCKED: this benchmark requires 4096-byte namespace blocks')
    print('ABI check passed. This does not yet validate a data-path read or authorize device handover.')


if __name__ == '__main__':
    main()
