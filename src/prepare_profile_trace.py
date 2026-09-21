#!/usr/bin/env python3
"""Generate a shared profile-based trace while reusing an existing dataset."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
from prepare_workload import SEED, IO_SIZE, SLOTS, MAGIC


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--source-workload', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=200)
    parser.add_argument('--warmups', type=int, default=10)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    source = json.loads(args.source_workload.read_text())
    if min(args.rounds, args.warmups) < 1 or profile['physical_io_bytes'] != IO_SIZE:
        raise ValueError('Invalid rounds or physical IO size')
    if source['io_size'] != IO_SIZE or source['data_bytes'] % IO_SIZE:
        raise ValueError('Incompatible source dataset')
    configs = []
    details = []
    for item in profile['derived_configurations']:
        batch = item['local_decode_batch']
        rate = item['reference_mean_miss_rate']
        n = round(batch * profile['top_k'] * rate)
        ppm = round(rate * 1_000_000)
        if (batch not in profile['local_decode_batch_sizes'] or n != item['n_reads']
            or not 0 < n <= min(SLOTS, source['data_bytes'] // IO_SIZE)
            or abs(rate - ppm / 1_000_000) > 1e-12):
            raise ValueError(f'Invalid derived configuration: {item}')
        scenario = next(s for s in profile['scenarios'] if s['name'] == item['scenario'])
        if scenario['reference_mean_miss_rate'] != rate:
            raise ValueError('Scenario rate mismatch')
        configs.append((batch, ppm, n))
        details.append(dict(item, effective_miss_rate=n/(batch*profile['top_k']),
                            gpu_cache_slots_per_request_per_layer=scenario['gpu_cache_slots_per_request_per_layer'],
                            reference_policy=scenario['policy']))
    if len(set(configs)) != len(configs) or not configs:
        raise ValueError('Empty or duplicate configurations')
    configs.sort()
    run = args.run_dir.resolve()
    run.mkdir(exist_ok=False)
    (run/'logs').mkdir()
    (run/'profile.json').write_text(json.dumps(profile, indent=2))
    nrecords = len(configs) * (args.rounds + args.warmups + 2)
    rng = np.random.Generator(np.random.PCG64(SEED))
    with (run/'trace.bin').open('xb') as stream:
        stream.write(struct.pack('<8sIIQII', MAGIC, IO_SIZE, SLOTS, source['data_bytes'], nrecords, SEED))
        for batch, ppm, n in configs:
            phases = [(2, 0)] + [(0, i) for i in range(args.warmups)]
            phases += [(1, i) for i in range(args.rounds)] + [(3, 0)]
            for phase, index in phases:
                stream.write(struct.pack('<5I', batch, ppm, n, phase, index))
                entries = np.empty((n, 2), dtype='<u4')
                entries[:, 0] = rng.choice(source['data_bytes']//IO_SIZE, n, replace=False)
                entries[:, 1] = rng.choice(SLOTS, n, replace=False)
                stream.write(entries.tobytes())
    meta = dict(source)
    meta.pop('mount', None)
    meta.update(seed=SEED, numpy_version=np.__version__, hbm_slots=SLOTS, hbm_bytes=SLOTS*IO_SIZE,
                trace_records=nrecords, rounds_per_configuration=args.rounds, warmups=args.warmups,
                configurations=configs, configuration_details=details, top_k=profile['top_k'],
                trace_sha256=hashlib.sha256((run/'trace.bin').read_bytes()).hexdigest(),
                source_workload=str(args.source_workload.resolve()),
                profile_sha256=hashlib.sha256((run/'profile.json').read_bytes()).hexdigest(),
                n_reads_formula=profile['n_reads_formula'], workload_kind='hisparse_mean_derived_synthetic_nvme',
                phase_design='fresh_sequential_abba', mapping_assumption=profile['mapping_assumption'])
    (run/'workload.json').write_text(json.dumps(meta, indent=2))
    print(json.dumps(dict(run_dir=str(run), configurations=configs, trace_records=nrecords,
                          trace_bytes=(run/'trace.bin').stat().st_size), indent=2))


if __name__ == '__main__':
    main()
