#!/usr/bin/env python3
"""Verify the committed GDS/public Tutti v0.1.1 comparison bundle."""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "results/key-comparison-cb-20260926"

def rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def check_raw(path, backend):
    data = rows(path)
    if len(data) != 2544:
        raise ValueError(f"{path}: expected 2544 rows, got {len(data)}")
    if any(r.get("backend") != backend or r.get("correct") != "true" or r.get("error") for r in data):
        raise ValueError(f"{path}: backend or data-validation field failed")
    measured = [r for r in data if r.get("phase") == "1"]
    if len(measured) != 2400:
        raise ValueError(f"{path}: expected 2400 measured rows, got {len(measured)}")
    return data

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--result-dir", type=Path, default=DEFAULT)
    args = p.parse_args()
    d = args.result_dir.resolve(strict=True)
    check_raw(d / "gds-A1.csv", "GDS")
    check_raw(d / "gds-A2.csv", "GDS")
    check_raw(d / "tutti-v011.csv", "Tutti-v0.1.1")
    comparison = rows(d / "comparison.csv")
    if len(comparison) != 12:
        raise ValueError(f"comparison.csv: expected 12 configurations, got {len(comparison)}")
    metadata = json.loads((d / "verification.json").read_text())
    if metadata.get("status") != "pass" or not metadata.get("all_rows_correct"):
        raise ValueError("verification.json does not record a passing comparison")
    if metadata.get("tutti_commit") != "38c8a68ab99c47a9a31f120b1018b6a7e01734d1":
        raise ValueError("unexpected public Tutti commit")
    print(f"PASS: {d} (3 x 2544 raw rows, 12 comparison rows, all data checks true)")

if __name__ == "__main__":
    main()
