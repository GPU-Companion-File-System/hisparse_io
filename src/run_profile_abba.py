#!/usr/bin/env python3
"""Run fresh A1/B1/B2/A2 on the same idle cb SSD in one GPU reservation."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import run_abba_continuation as w


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve(strict=True)
    if os.environ.get('CUDA_VISIBLE_DEVICES') != '0':
        raise SystemExit('Use canhazgpu reservation for physical GPU 0')
    lock = (w.ROOT/'build/cb-resource.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    meta = json.loads((run/'workload.json').read_text())
    if hashlib.sha256((run/'trace.bin').read_bytes()).hexdigest() != meta['trace_sha256']:
        raise RuntimeError('Trace hash mismatch')
    for name in ('operations.json', 'raw-A1.csv', 'raw-B1.csv', 'raw-B2.csv', 'raw-A2.csv'):
        if (run/name).exists():
            raise RuntimeError(f'Refusing overwrite: {name}')
    initial = w.driver()
    if initial not in (None, 'nvme'):
        raise RuntimeError(f'cb owned by {initial}')
    if subprocess.run(['mountpoint', '-q', str(w.MOUNT)]).returncode == 0:
        raise RuntimeError('Experiment mount busy')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 50173))
    events = []
    daemon = None
    child = None
    mounted = False
    touched = False
    data = Path(meta['data_path'])

    def event(stage, **extra):
        events.append(dict(stage=stage, timestamp=time.time(), **extra))
        (run/'operations.json').write_text(json.dumps(events, indent=2))
        print(stage, extra, flush=True)

    def native_device():
        device = w.block_for_bdf('nvme')
        serial = (Path('/sys/class/block')/Path(device).name/'device/serial').read_text().strip()
        if serial != w.SERIAL:
            raise RuntimeError('Serial mismatch')
        w.unmounted_device(device)
        w.check_uuid(device)
        return device

    def verify_data(when):
        h = hashlib.sha256()
        with data.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 << 20), b''):
                h.update(chunk)
        if h.hexdigest() != meta['data_sha256']:
            raise RuntimeError(f'{when} dataset hash mismatch')
        event('data_sha256_verified', when=when, sha256=h.hexdigest())

    def benchmark(phase, device):
        nonlocal child
        logdir = run/'logs'/phase
        logdir.mkdir()
        env = dict(os.environ)
        if phase.startswith('A'):
            cfg = json.loads((w.ROOT/'configs/cufile.json').read_text())
            cfg['logging']['dir'] = str(logdir)
            cfg_path = run/f'cufile-{phase}.json'
            cfg_path.write_text(json.dumps(cfg, indent=2))
            env['CUFILE_ENV_PATH_JSON'] = str(cfg_path)
            command = [str(w.ROOT/'build/gds_bench'), str(data), str(run/'trace.bin'), str(run/f'raw-{phase}.csv')]
        else:
            command = ['sudo', '-n', 'env', 'CUDA_VISIBLE_DEVICES=0', f'LD_LIBRARY_PATH={w.SHARED_LD}',
                       str(w.ROOT/'build/tutti_shared_bench'), str(data), str(run/'trace.bin'),
                       str(run/f'raw-{phase}.csv'), '0', w.BDF, '127.0.0.1:50173']
        with (run/f'logs/{phase}.log').open('x') as log:
            log.write('COMMAND: ' + json.dumps(command) + '\n'); log.flush()
            event('phase_start', phase=phase, device=device, bdf=w.BDF, uuid=w.UUID,
                  cuda_visible_devices=os.environ['CUDA_VISIBLE_DEVICES'])
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                     env=env, start_new_session=True)
            code = child.wait(timeout=600)
            child = None
            log.write(f'\nEXIT: {code}\n')
            event('phase_end', phase=phase, exit_code=code)
            if code:
                raise RuntimeError(f'{phase} failed')

    def stop_daemon():
        nonlocal daemon
        if daemon is None:
            return
        if daemon.poll() is None:
            # Target sudo once; a process-group signal can reach its child twice.
            w.command(['sudo', '-n', 'kill', '-TERM', str(daemon.pid)])
        code = daemon.wait(timeout=45)
        daemon = None
        if code != 0 or subprocess.run(['mountpoint', '-q', str(w.MOUNT)]).returncode == 0 or w.driver() is not None:
            raise RuntimeError(f'Daemon teardown incomplete (exit={code}, driver={w.driver()})')
        event('daemon_stopped_cleanly')

    try:
        if initial is None:
            w.sysfs_driver_write('nvme', 'bind'); touched = True
        device = native_device()
        event('preflight_pass', bdf=w.BDF, serial=w.SERIAL, uuid=w.UUID, initial_driver=initial)
        w.command(['sudo', '-n', 'mount', '-t', 'ext4', '-o', 'data=ordered', device, str(w.MOUNT)])
        mounted = True
        verify_data('before')
        benchmark('A1', device)
        w.command(['sudo', '-n', 'umount', str(w.MOUNT)]); mounted = False
        w.unmounted_device(device)
        w.sysfs_driver_write('nvme', 'unbind'); touched = True
        event('stock_nvme_unbound')
        with (run/'logs/daemon-cb.log').open('x') as log:
            daemon = subprocess.Popen(['sudo', '-n', 'env', 'CUDA_VISIBLE_DEVICES=0', f'LD_LIBRARY_PATH={w.SHARED_LD}',
                str(w.SHARED_BUILD/'bin/tutti_daemon'), '--config', str(run/'daemon-cb.yaml')],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (run/'daemon-process.json').write_text(json.dumps(dict(sudo_pid=daemon.pid,
            binary=str(w.SHARED_BUILD/'bin/tutti_daemon'), endpoint='127.0.0.1:50173'), indent=2))
        deadline = time.monotonic() + 60
        while True:
            if daemon.poll() is not None:
                raise RuntimeError('Daemon exited during startup')
            try:
                with socket.create_connection(('127.0.0.1', 50173), timeout=.25):
                    device = w.block_for_bdf('snvme')
                    break
            except (OSError, RuntimeError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Daemon startup timed out')
                time.sleep(.1)
        w.check_uuid(device)
        mounts = json.loads(subprocess.check_output(['findmnt', '-J', '-M', str(w.MOUNT), '-o', 'SOURCE,FSTYPE'], text=True))['filesystems']
        if len(mounts) != 1 or mounts[0]['source'] != device or mounts[0]['fstype'] != 'ext4':
            raise RuntimeError(f'Wrong daemon-owned mount: {mounts}')
        event('tutti_device_mounted', device=device, bdf=w.BDF, uuid=w.UUID)
        benchmark('B1', device)
        benchmark('B2', device)
        stop_daemon()
        w.sysfs_driver_write('nvme', 'bind')
        device = native_device()
        w.command(['sudo', '-n', 'mount', '-t', 'ext4', '-o', 'data=ordered', device, str(w.MOUNT)])
        mounted = True
        benchmark('A2', device)
        verify_data('after')
    finally:
        if child is not None and child.poll() is None:
            w.command(['sudo', '-n', 'kill', '-TERM', str(child.pid)])
            child.wait(timeout=30)
        if mounted:
            w.command(['sudo', '-n', 'umount', str(w.MOUNT)])
        stop_daemon()
        if touched and w.driver() == 'nvme' and initial is None:
            w.unmounted_device(w.block_for_bdf('nvme'))
            w.sysfs_driver_write('nvme', 'unbind')
        elif touched and w.driver() is None and initial == 'nvme':
            w.sysfs_driver_write('nvme', 'bind')
        event('resources_released', final_driver=w.driver())


if __name__ == '__main__':
    main()
