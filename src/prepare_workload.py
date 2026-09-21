#!/usr/bin/env python3
"""Create immutable, fully written data and a shared deterministic binary trace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import numpy as np

SEED = 20260907
IO_SIZE = 4096
SLOTS = 65536  # 256 MiB, identical for either backend
MAGIC = b"HSPTRC01"
BASE = np.uint64(0xD6E8FEB86659FD93)
STEP = np.uint64(0x9E3779B97F4A7C15)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--gib", type=int, default=16)
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--warmups", type=int, default=10)
    a = parser.parse_args()
    if a.gib < 1 or a.rounds < 1 or a.warmups < 1:
        parser.error("sizes and round counts must be positive")
    data = a.data.absolute()
    run = a.run_dir.resolve(strict=True)
    data.parent.mkdir(parents=True, exist_ok=True)
    mount = json.loads(subprocess.check_output(
        ["findmnt", "-J", "-T", str(data.parent)], text=True))["filesystems"][0]
    source = mount["source"]
    if mount["fstype"] != "ext4" or not source.startswith(("/dev/nvme", "/dev/snvme")):
        raise SystemExit(f"Refusing non-NVMe ext4 storage: {mount}")
    size = a.gib << 30
    stat = os.statvfs(data.parent)
    if size > stat.f_bavail * stat.f_frsize // 5:
        raise SystemExit("Dataset exceeds 20% of available space")
    blocks = size // IO_SIZE
    if blocks > 2**32:
        raise SystemExit("Trace block IDs are uint32")
    # O_EXCL prohibits replacing an existing dataset. Every byte is written;
    # no fallocate-only or sparse-file read can be mistaken for SSD IO.
    columns = np.arange(512, dtype=np.uint64) * STEP
    h = hashlib.sha256()
    with data.open("xb", buffering=0) as stream:
        for first in range(0, blocks, 4096):
            ids = np.arange(first, min(first + 4096, blocks), dtype=np.uint64)
            values = ((ids[:, None] << np.uint64(32)) ^ BASE ^ columns).astype("<u8")
            view = memoryview(values).cast("B")
            h.update(view)
            while view:
                count = stream.write(view)
                if not count:
                    raise OSError("Short/zero data write")
                view = view[count:]
        os.fsync(stream.fileno())
    if data.stat().st_blocks * 512 < size:
        raise SystemExit("File not fully allocated after writing")
    configurations = [(b, ppm, b * round(2048 * ppm / 1_000_000))
                      for b in (1, 10, 100) for ppm in (1000, 10000, 50000, 200000)]
    nrecords = len(configurations) * (a.rounds + a.warmups + 2)
    trace = run / "trace.bin"
    rng = np.random.Generator(np.random.PCG64(SEED))
    with trace.open("xb") as stream:
        stream.write(struct.pack("<8sIIQII", MAGIC, IO_SIZE, SLOTS, size, nrecords, SEED))
        for batch, ppm, n in configurations:
            phases = [(2, 0)] + [(0, i) for i in range(a.warmups)]
            phases += [(1, i) for i in range(a.rounds)] + [(3, 0)]
            for phase, index in phases:
                stream.write(struct.pack("<IIIII", batch, ppm, n, phase, index))
                entries = np.empty((n, 2), dtype="<u4")
                entries[:, 0] = rng.choice(blocks, n, replace=False)
                entries[:, 1] = rng.choice(SLOTS, n, replace=False)
                stream.write(entries.tobytes())
    metadata = {
        "schema": "HSPTRC01", "seed": SEED, "rng": "numpy.PCG64",
        "numpy_version": np.__version__, "data_path": str(data), "data_bytes": size,
        "data_sha256": h.hexdigest(), "trace_sha256": digest(trace),
        "io_size": IO_SIZE, "hbm_slots": SLOTS, "hbm_bytes": SLOTS * IO_SIZE,
        "rounds_per_configuration": a.rounds, "warmups": a.warmups,
        "trace_records": nrecords, "queue_depth": 256, "submission_group": 16,
        "unique_offsets_and_slots_per_round": True,
        "pattern_u64": "(block_id << 32) XOR 0xD6E8FEB86659FD93 XOR (word_index * 0x9E3779B97F4A7C15 modulo 2^64)",
        "mount": mount, "configurations": configurations,
        "phase_codes": {"0": "warmup", "1": "measurement", "2": "check_before", "3": "check_after"},
    }
    with (run / "workload.json").open("x") as stream:
        json.dump(metadata, stream, indent=2)
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
