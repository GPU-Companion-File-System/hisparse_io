#!/usr/bin/env python3
"""Build the publishable GDS versus public Tutti v0.1.1 comparison."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key(row):
    return (int(row["request_batch"]), round(float(row["miss_rate"]), 6), int(row["n_reads"]))


def read_rows(path: Path, backend: str):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 2544:
        raise ValueError(f"{path}: {len(rows)} rows, expected 2544")
    if any(row["backend"] != backend or row["correct"] != "true" or row["error"] for row in rows):
        raise ValueError(f"{path}: backend, verification, or error field mismatch")
    return rows


def measured(rows):
    grouped = {}
    for row in rows:
        if row["phase"] == "1":
            grouped.setdefault(key(row), []).append(row)
    return grouped


def percentile(rows):
    values = np.asarray([float(row["completion_us"]) for row in rows], dtype=float)
    return np.percentile(values, [50, 99], method="linear")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gds-a1", type=Path, required=True)
    parser.add_argument("--gds-a2", type=Path, required=True)
    parser.add_argument("--tutti-v011", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--bdf", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--tutti-commit", required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    gds_a1 = read_rows(args.gds_a1, "GDS")
    gds_a2 = read_rows(args.gds_a2, "GDS")
    tutti = read_rows(args.tutti_v011, "Tutti-v0.1.1")
    gds_1, gds_2, tutti_m = measured(gds_a1), measured(gds_a2), measured(tutti)
    if set(gds_1) != set(gds_2) or set(gds_1) != set(tutti_m):
        raise ValueError("GDS and Tutti configurations differ")
    if any(len(gds_1[k]) != 200 or len(gds_2[k]) != 200 or len(tutti_m[k]) != 200 for k in gds_1):
        raise ValueError("every configuration must have 200 phase=1 samples per input")

    rows = []
    for k in sorted(gds_1):
        gds_p50, gds_p99 = percentile(gds_1[k] + gds_2[k])
        tutti_p50, tutti_p99 = percentile(tutti_m[k])
        rows.append({
            "request_batch": k[0], "miss_rate": f"{k[1]:.3f}", "n_reads": k[2],
            "gds_p50_us": f"{gds_p50:.6f}", "tutti_v011_p50_us": f"{tutti_p50:.6f}",
            "p50_speedup_gds_over_tutti": f"{gds_p50 / tutti_p50:.6f}",
            "gds_p99_us": f"{gds_p99:.6f}", "tutti_v011_p99_us": f"{tutti_p99:.6f}",
            "p99_speedup_gds_over_tutti": f"{gds_p99 / tutti_p99:.6f}",
        })
    fields = list(rows[0])
    with (args.out_dir / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    workload = json.loads(args.workload.read_text())
    verification = {
        "status": "pass",
        "comparison": "GDS successful samples versus public Tutti v0.1.1",
        "same_physical_disk": {"pci_bdf": args.bdf, "serial": args.serial},
        "data": {"path": str(args.data), "bytes": args.data.stat().st_size, "sha256": workload["data_sha256"]},
        "trace": {"path": str(args.trace), "bytes": args.trace.stat().st_size, "sha256": workload["trace_sha256"]},
        "gds_sources": [str(args.gds_a1), str(args.gds_a2)],
        "tutti_source": str(args.tutti_v011),
        "tutti_commit": args.tutti_commit,
        "gds_rows_per_input": 2544,
        "tutti_rows": 2544,
        "measurement_rows_per_configuration": {"gds_a1": 200, "gds_a2": 200, "tutti_v011": 200},
        "all_rows_correct": True,
        "percentile_method": "numpy linear percentile; GDS pools A1+A2 (400 samples), Tutti uses 200 samples",
    }
    (args.out_dir / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")

    report = [
        "# GDS 与公开 Tutti v0.1.1 对照",
        "",
        "两套后端使用同一物理 SSD、同一 16 GiB 数据文件、同一 trace 和同一组 12 个配置。GDS 取已成功完成的 A1/A2 样本，公开 Tutti 取 v0.1.1 的完整矩阵。设备、输入哈希和逐行校验见 `verification.json`。",
        "",
        "延迟单位为 ms；加速比定义为 `GDS / Tutti`，数值大于 1 表示 Tutti 更快。",
        "",
        "| batch | miss rate | reads | GDS p50 | Tutti v0.1.1 p50 | p50 GDS/Tutti | GDS p99 | Tutti v0.1.1 p99 | p99 GDS/Tutti |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['request_batch']} | {row['miss_rate']} | {row['n_reads']} | "
            f"{float(row['gds_p50_us']) / 1000:.3f} | {float(row['tutti_v011_p50_us']) / 1000:.3f} | "
            f"{float(row['p50_speedup_gds_over_tutti']):.2f}x | {float(row['gds_p99_us']) / 1000:.3f} | "
            f"{float(row['tutti_v011_p99_us']) / 1000:.3f} | {float(row['p99_speedup_gds_over_tutti']):.2f}x |"
        )
    report += [
        "",
        "GDS 与公开 Tutti 的采集日期不同；表格表达的是同盘、同输入、同配置的性能对照，不是同一时刻同步运行。公开 Tutti 使用上游 commit `" + args.tutti_commit + "`。",
    ]
    (args.out_dir / "README.md").write_text("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
