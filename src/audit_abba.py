#!/usr/bin/env python3
"""Audit existing phase logs and data hashes before allowing ABBA comparison."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event(events, stage, phase=None):
    matches=[e for e in events if e['stage']==stage and (phase is None or e.get('phase')==phase)]
    if len(matches)!=1:
        raise ValueError(f'Expected one {stage}/{phase} event')
    return matches[0]


def audit_gds(log, rows):
    text=log.read_text()
    checks=('properties.use_compat_mode : false','properties.force_compat_mode : false',
            'nvidia_fs driver version check ok','nvidia_fs driver closed')
    if not all(x in text for x in checks):
        raise ValueError(f'GDS path evidence missing: {log}')
    counts={}
    for name in ('BatchSubmit','BatchComplete','PosixBatchEnqueued','PosixBatchProcessed','BufRegister','BufDeregister'):
        found=re.findall(r'^'+name+r': ok = (\d+) err = (\d+)$',text,re.M)
        if len(found)!=1 or int(found[0][1])!=0:
            raise ValueError(f'Invalid {name} counters in {log}')
        counts[name]=int(found[0][0])
    batches=sum((int(r['n_reads'])+15)//16 for r in rows)
    expected=dict(BatchSubmit=batches,BatchComplete=batches,PosixBatchEnqueued=0,
                  PosixBatchProcessed=0,BufRegister=256,BufDeregister=256)
    if counts!=expected:
        raise ValueError(f'GDS counters do not match CSV requests: {counts} != {expected}')
    return dict(evidence=str(log),sha256=digest(log),counters=counts,
                compatibility_allowed=False,path='cuFile batch / nvidia_fs')


def audit_fresh(run, meta):
    events = json.loads((run/'operations.json').read_text())
    pre = event(events, 'preflight_pass')
    release = event(events, 'resources_released')
    if release['final_driver'] != pre['initial_driver']:
        raise ValueError('Device state not restored')
    hashes = [e for e in events if e['stage'] == 'data_sha256_verified']
    if ([e['when'] for e in hashes] != ['before', 'after']
        or any(e['sha256'] != meta['data_sha256'] for e in hashes)
        or digest(run/'trace.bin') != meta['trace_sha256']
        or digest(run/'profile.json') != meta['profile_sha256']):
        raise ValueError('Dataset, profile or trace fingerprint mismatch')
    mount = event(events, 'tutti_device_mounted')
    if (mount['bdf'], mount['uuid']) != (pre['bdf'], pre['uuid']):
        raise ValueError('Tutti filesystem identity mismatch')
    daemon_log = (run/'logs/daemon-cb.log').read_text()
    event(events, 'daemon_stopped_cleanly')
    if 'tutti_daemon exited cleanly.' not in daemon_log or 'force-exit requested' in daemon_log:
        raise ValueError('Daemon did not exit cleanly')
    gpu = None
    phases = {}
    for p in ('A1', 'B1', 'B2', 'A2'):
        start = event(events, 'phase_start', p)
        end = event(events, 'phase_end', p)
        if (end['exit_code'] != 0 or end['timestamp'] <= start['timestamp']
            or start['bdf'] != pre['bdf'] or start['uuid'] != pre['uuid']
            or start['cuda_visible_devices'] != '0'):
            raise ValueError(f'{p}: failed phase or identity mismatch')
        path = run/f'raw-{p}.csv'
        rows = list(csv.DictReader(path.open()))
        if len(rows) != meta['trace_records'] or any(r['correct'] != 'true' or r['error'] for r in rows):
            raise ValueError(f'{p}: incomplete or failed samples')
        item = dict(raw_file=str(path), raw_sha256=digest(path), rows=len(rows),
                    bdf=pre['bdf'], start=start['timestamp'], end=end['timestamp'], all_reads_verified=True)
        log = run/f'logs/{p}.log'
        text = log.read_text()
        if p.startswith('A'):
            found = re.findall(r'^GPU=(\S+)', text, re.M)
            if len(found) != 1 or (gpu is not None and found[0].lower() != gpu):
                raise ValueError('GPU identity mismatch')
            gpu = found[0].lower()
            logs = list((run/'logs'/p).glob('cufile_*.log'))
            if len(logs) != 1:
                raise ValueError(f'{p}: ambiguous cuFile evidence')
            item['direct_path'] = audit_gds(logs[0], rows)
        else:
            if (f"Tutti-deployed BDF={pre['bdf']} device={mount['device']}" not in text
                or start['device'] != mount['device'] or 'CUDA_VISIBLE_DEVICES=0' not in text
                or any(r['direct_path'] != 'gpu_nvme_kernel' for r in rows)):
                raise ValueError(f'{p}: invalid Tutti path evidence')
            item['direct_path'] = dict(path='deployed launch_pool_file_xfer GPU kernel', evidence=str(log), sha256=digest(log))
        phases[p] = item
    order = ('A1', 'B1', 'B2', 'A2')
    if any(phases[a]['end'] > phases[b]['start'] for a,b in zip(order, order[1:])):
        raise ValueError('Unexpected ABBA phase order')
    for item in phases.values():
        item['gpu'] = gpu
        item['trace_sha256'] = meta['trace_sha256']
    audit = dict(status='verified', phase_design='fresh_sequential_abba', phases=phases,
                 bdf=pre['bdf'], serial=pre['serial'], uuid=pre['uuid'],
                 data_sha256=meta['data_sha256'], trace_sha256=meta['trace_sha256'],
                 timing_caveat='All four stages freshly measured sequentially; device handovers and separate initialization remain.',
                 events={'operations.json': digest(run/'operations.json')}, audit_script_sha256=digest(Path(__file__)))
    with (run/'phase-audit.json').open('x') as stream:
        json.dump(audit, stream, indent=2)
    print('PASS: fresh ABBA, data/trace/profile identities, strict direct paths and clean teardown')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    run=args.run_dir.resolve()
    meta=json.loads((run/'workload.json').read_text())
    if meta.get('phase_design') == 'fresh_sequential_abba':
        audit_fresh(run, meta)
        return
    prior=json.loads((run/'DIRECT_PATH-A1.json').read_text())
    before=json.loads((run/'operations.json').read_text())
    after=json.loads((run/'operations-A2.json').read_text())
    pre_b=event(before,'preflight_pass'); pre_a=event(after,'preflight_pass')
    mount_b=event(before,'tutti_device_mounted'); mount_a=event(after,'gds_device_mounted')
    if pre_a['bdf']!=pre_b['bdf'] or pre_a['serial']!=pre_b['serial'] or prior['data_device']!=pre_a['bdf']:
        raise ValueError('Physical device mismatch')
    if mount_a['uuid']!=mount_b['uuid'] or mount_a['uuid']!=pre_a['uuid']:
        raise ValueError('Filesystem UUID mismatch')
    data_event=event(after,'data_sha256_verified')
    if data_event['sha256']!=meta['data_sha256'] or digest(run/'trace.bin')!=meta['trace_sha256']:
        raise ValueError('Data/trace hash mismatch')
    if event(after,'resources_released')['final_driver'] is not None:
        raise ValueError('A2 did not release its device')
    phases={}
    for p in ('A1','B1','B2','A2'):
        path=run/f'raw-{p}.csv'
        rows=list(csv.DictReader(path.open()))
        if len(rows)!=meta['trace_records'] or any(r['correct']!='true' or r['error'] for r in rows):
            raise ValueError(f'{p}: incomplete or failed data')
        item=dict(raw_file=str(path),raw_sha256=digest(path),bdf=pre_a['bdf'],
                  gpu=prior['gpu'],trace_sha256=meta['trace_sha256'],rows=len(rows),all_reads_verified=True)
        if p!='A1':
            ev=before if p.startswith('B') else after
            start=event(ev,'phase_start',p); end=event(ev,'phase_end',p)
            if end['exit_code']!=0:
                raise ValueError(f'{p}: failed exit')
            item.update(start=start['timestamp'],end=end['timestamp'])
        if p.startswith('A'):
            if p=='A1':
                provenance=json.loads((run/'A1-provenance.json').read_text())
                if digest(Path(provenance['raw_source']))!=digest(path):
                    raise ValueError('A1 differs from original measured data')
                log=Path(prior['evidence'])
            else:
                logs=list((run/'logs').glob('cufile_*.log'))
                if len(logs)!=1:
                    raise ValueError('Ambiguous A2 cuFile log')
                log=logs[0]
                if f"GPU={prior['gpu'].upper()}" not in (run/'logs/A2.log').read_text():
                    raise ValueError('A2 GPU identity differs from A1')
            item['direct_path']=audit_gds(log,rows)
        else:
            log=run/f'logs/{p}.log'
            text=log.read_text()
            if (f"Tutti-deployed BDF={pre_a['bdf']} device={mount_b['device']}" not in text
                or 'CUDA_VISIBLE_DEVICES=0' not in text
                or any(r['direct_path']!='gpu_nvme_kernel' for r in rows)):
                raise ValueError(f'{p}: missing Tutti device/path evidence')
            item['direct_path']=dict(path='deployed launch_pool_file_xfer GPU kernel',evidence=str(log),sha256=digest(log))
        phases[p]=item
    if not phases['B1']['end']<=phases['B2']['start']<phases['B2']['end']<=phases['A2']['start']:
        raise ValueError('Unexpected phase order')
    regression=(run/'daemon-regression/logs/daemon-cb.log').read_text()
    if 'tutti_daemon exited cleanly.' not in regression or 'force-exit requested' in regression:
        raise ValueError('Graceful daemon shutdown regression failed')
    audit=dict(status='verified',bdf=pre_a['bdf'],serial=pre_a['serial'],uuid=pre_a['uuid'],
        data_sha256=meta['data_sha256'],trace_sha256=meta['trace_sha256'],phases=phases,
        timing_caveat='A1 is historical; B2 to A2 includes teardown recovery and a startup/shutdown regression; descriptive comparison only',
        events={name:digest(run/name) for name in ('operations.json','operations-A2.json','teardown-recovery.json')},
        audit_script_sha256=digest(Path(__file__)))
    with (run/'phase-audit.json').open('x') as f:
        json.dump(audit,f,indent=2)
    print('PASS: four complete phases, device/trace/data identities, strict GDS path, Tutti path, graceful teardown')


if __name__=='__main__':
    main()
