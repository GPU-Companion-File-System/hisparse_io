#!/usr/bin/env python3
"""Make a strict historical-GDS/current-public-Tutti comparison table."""
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


def percentile(rows):
    values = np.asarray([float(row["completion_us"]) for row in rows], dtype=float)
    return np.percentile(values, [50, 99], method="linear")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-comparison", type=Path, required=True)
    parser.add_argument("--public-raw", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--bdf", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--public-commit", required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    with args.historical_comparison.open(newline="") as stream:
        historical = {key(row): row for row in csv.DictReader(stream)}
    with args.public_raw.open(newline="") as stream:
        public_rows = list(csv.DictReader(stream))
    if len(public_rows) != 2544:
        raise ValueError(f"public raw rows: {len(public_rows)} != 2544")
    if any(row["backend"] != "Tutti-v0.1.1" or row["correct"] != "true" or row["error"] for row in public_rows):
        raise ValueError("public raw contains an invalid row")
    measured = {}
    for row in public_rows:
        if row["phase"] == "1":
            measured.setdefault(key(row), []).append(row)
    if set(measured) != set(historical) or any(len(rows) != 200 for rows in measured.values()):
        raise ValueError("public configurations or measurement counts differ from historical table")

    rows = []
    for k in sorted(historical):
        old = historical[k]
        p50, p99 = percentile(measured[k])
        gds_p50 = float(old["gds_p50_us"])
        gds_p99 = float(old["gds_p99_us"])
        rows.append({
            "request_batch": k[0],
            "miss_rate": f"{k[1]:.3f}",
            "n_reads": k[2],
            "gds_historical_p50_us": f"{gds_p50:.6f}",
            "gds_historical_p99_us": f"{gds_p99:.6f}",
            "tutti_public_v011_p50_us": f"{p50:.6f}",
            "tutti_public_v011_p99_us": f"{p99:.6f}",
            "p50_speedup_gds_over_public": f"{gds_p50 / p50:.6f}",
            "p99_speedup_gds_over_public": f"{gds_p99 / p99:.6f}",
        })
    fields = list(rows[0])
    with (args.out_dir / "comparison.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "status": "pass",
        "comparison": "historical GDS A1+A2 versus current public Tutti v0.1.1",
        "same_physical_disk": {"pci_bdf": args.bdf, "serial": args.serial},
        "data": {"path": str(args.data), "bytes": args.data.stat().st_size, "sha256": sha256(args.data)},
        "trace": {"path": str(args.trace), "bytes": args.trace.stat().st_size, "sha256": sha256(args.trace)},
        "historical_gds_source": str(args.historical_comparison),
        "public_tutti_source": str(args.public_raw),
        "public_tutti_commit": args.public_commit,
        "public_rows": len(public_rows),
        "public_measurement_rows": sum(len(rows) for rows in measured.values()),
        "all_public_rows_correct": True,
        "percentile_method": "numpy linear percentile over 200 phase=1 rows per configuration",
        "limitation": "GDS values are historical 2026-09-07 A1+A2 samples; public Tutti values are current 2026-09-26 samples.",
    }
    (args.out_dir / "verification.json").write_text(json.dumps(metadata, indent=2) + "\n")

    report = [
        "# 关键对照：历史 GDS 与公开 Tutti v0.1.1",
        "",
        "同一物理 SSD（`0000:cb:00.0`）、同一 16 GiB 数据文件、同一 trace。GDS 使用 2026-09-07 已成功完成的 A1+A2 合并样本；Tutti 使用 2026-09-26 公开 v0.1.1 在同一 SSD 上的新测量。",
        "",
        "延迟单位为 ms；加速比定义为 GDS / Tutti，数值大于 1 表示 Tutti 更快。",
        "",
        "| batch | miss rate | reads | GDS p50 | public Tutti p50 | p50 GDS/Tutti | GDS p99 | public Tutti p99 | p99 GDS/Tutti |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['request_batch']} | {row['miss_rate']} | {row['n_reads']} | "
            f"{float(row['gds_historical_p50_us']) / 1000:.3f} | "
            f"{float(row['tutti_public_v011_p50_us']) / 1000:.3f} | "
            f"{float(row['p50_speedup_gds_over_public']):.2f}x | "
            f"{float(row['gds_historical_p99_us']) / 1000:.3f} | "
            f"{float(row['tutti_public_v011_p99_us']) / 1000:.3f} | "
            f"{float(row['p99_speedup_gds_over_public']):.2f}x |"
        )
    report += [
        "",
        "数据和 trace 的 SHA-256、行数与限制见 `verification.json`。这是严格输入/设备对照，但不是同一时刻运行：GDS 样本来自历史成功运行，当前主机后来出现 GDS DMA 映射故障。",
    ]
    (args.out_dir / "KEY_COMPARISON.md").write_text("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
