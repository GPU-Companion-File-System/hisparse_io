#!/usr/bin/env python3
"""Run B1/B2/A2 on idle cb, using existing modules and shared Tutti build."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BDF = "0000:cb:00.0"
SERIAL = "PHCP418201G07P6CGN"
UUID = "4885b88d-00be-4e57-86a8-2c1f837e4917"
MOUNT = Path("/mnt/hisparse_io")
SHARED_BUILD = Path("/home/zwh/lmcache-dev/.build/vllm027-torch213-cu130/geminifs")
SHARED_CUDA = Path("/home/zwh/.venvs/lmcache-mooncake-latest/lib/python3.12/site-packages/nvidia/cu13")
SHARED_LD = f"{SHARED_BUILD}/lib:{SHARED_CUDA}/lib:/home/zwh/anaconda3/lib"


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def driver():
    p = Path("/sys/bus/pci/devices") / BDF / "driver"
    return p.resolve().name if p.is_symlink() else None


def block_for_bdf(prefix):
    matches = [p for p in Path("/sys/class/block").glob(prefix + "*n1")
               if f"/{BDF}/" in str((p / "device").resolve())]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {prefix} block for {BDF}: {matches}")
    return "/dev/" + matches[0].name


def sysfs_driver_write(name, operation):
    path = f"/sys/bus/pci/drivers/{name}/{operation}"
    command(["sudo", "-n", "python3", "-c",
             "import sys; open(sys.argv[1], 'w').write(sys.argv[2])", path, BDF])


def unmounted_device(device):
    p = subprocess.run(["findmnt", "-rn", "-S", device], capture_output=True, text=True)
    if p.stdout.strip():
        raise RuntimeError(f"Device already mounted: {p.stdout.strip()}")
    p = subprocess.run(["sudo", "-n", "fuser", device], capture_output=True, text=True)
    if p.returncode == 0:
        raise RuntimeError(f"Device has an open user: {p.stdout} {p.stderr}")
    if p.returncode != 1:
        raise RuntimeError(f"Cannot determine device users: {p.stderr}")


def check_uuid(device):
    actual = subprocess.check_output(["sudo", "-n", "blkid", "-p", "-s", "UUID", "-o", "value", device], text=True).strip()
    if actual != UUID:
        raise RuntimeError(f"Unexpected UUID for {device}: {actual}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--startup-only", action="store_true", help="Check daemon mount and graceful teardown without running benchmarks")
    a = p.parse_args()
    run = a.run_dir.resolve(strict=True)
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise SystemExit("Must run in canhazgpu reservation for physical GPU 0")
    lock = (ROOT / "build/cb-resource.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if driver() != "nvme":
        raise SystemExit("cb must initially be idle on stock nvme")
    device = block_for_bdf("nvme")
    if (Path("/sys/class/block") / Path(device).name / "device/serial").read_text().strip() != SERIAL:
        raise SystemExit("NVMe serial mismatch")
    unmounted_device(device)
    check_uuid(device)
    if subprocess.run(["mountpoint", "-q", str(MOUNT)]).returncode == 0:
        raise SystemExit("Experiment mountpoint is busy")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 50173))
    meta = json.loads((run / "workload.json").read_text())
    if hashlib.sha256((run / "trace.bin").read_bytes()).hexdigest() != meta["trace_sha256"]:
        raise SystemExit("Trace hash mismatch")
    data = MOUNT / "hisparse_io_byh/bench-20260907-083221.bin"
    events = []
    daemon = None
    mounted = False
    touched = False
    child = None

    def event(stage, **extra):
        row = dict(stage=stage, timestamp=time.time(), **extra)
        events.append(row)
        (run / "operations.json").write_text(json.dumps(events, indent=2))
        print(stage, extra, flush=True)

    def stop_our_daemon():
        nonlocal daemon
        if daemon is not None and daemon.poll() is None:
            # Signal sudo only: it forwards once to its child. A group signal
            # also reaches the daemon directly, making its second-signal
            # handler force-exit before unmounting the filesystem.
            command(["sudo", "-n", "kill", "-TERM", str(daemon.pid)])
            try:
                daemon.wait(timeout=25)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Own daemon did not exit; refusing to force-kill or touch shared services")
        daemon = None
        if subprocess.run(["mountpoint", "-q", str(MOUNT)]).returncode == 0:
            raise RuntimeError("Daemon teardown left the experiment mount active")

    try:
        event("preflight_pass", bdf=BDF, serial=SERIAL, device=device)
        sysfs_driver_write("nvme", "unbind")
        touched = True
        event("stock_nvme_unbound")
        daemon_log = (run / "logs/daemon-cb.log").open("x")
        daemon = subprocess.Popen(["sudo", "-n", "env", f"CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']}", f"LD_LIBRARY_PATH={SHARED_LD}",
            str(SHARED_BUILD / "bin/tutti_daemon"), "--config", str(run / "daemon-cb.yaml")],
            stdout=daemon_log, stderr=subprocess.STDOUT, start_new_session=True)
        (run / "daemon-process.json").write_text(json.dumps({"process_group": daemon.pid,
            "binary": str(SHARED_BUILD / "bin/tutti_daemon"), "endpoint": "127.0.0.1:50173"}, indent=2))
        deadline = time.monotonic() + 60
        while True:
            if daemon.poll() is not None:
                raise RuntimeError("Independent daemon exited during startup; inspect daemon-cb.log")
            try:
                with socket.create_connection(("127.0.0.1", 50173), timeout=.25):
                    device = block_for_bdf("snvme")
                    break
            except (OSError, RuntimeError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Independent daemon startup timed out")
                time.sleep(.1)
        check_uuid(device)
        # The deployed daemon owns the mount and removes accelerator views
        # before unmounting it on shutdown. Never mount/unmount over its owner.
        mount_info = json.loads(subprocess.check_output(
            ["findmnt", "-J", "-M", str(MOUNT), "-o", "SOURCE,TARGET,FSTYPE"], text=True))["filesystems"]
        if len(mount_info) != 1 or mount_info[0]["source"] != device or mount_info[0]["fstype"] != "ext4":
            raise RuntimeError(f"Unexpected daemon-owned mount: {mount_info}")
        event("tutti_device_mounted", device=device, uuid=UUID, owner="experiment_daemon")
        if a.startup_only:
            return
        for phase in ["B1", "B2"]:
            output = run / f"raw-{phase}.csv"
            with (run / f"logs/{phase}.log").open("x") as log:
                args = ["sudo", "-n", "env", "CUDA_VISIBLE_DEVICES=0", f"LD_LIBRARY_PATH={SHARED_LD}",
                    str(ROOT / "build/tutti_shared_bench"), str(data), str(run / "trace.bin"),
                    str(output), "0", BDF, "127.0.0.1:50173"]
                log.write("COMMAND: " + json.dumps(args) + "\n"); log.flush()
                event("phase_start", phase=phase, device=device)
                child = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                code = child.wait(timeout=600)
                child = None
                log.write(f"\nEXIT: {code}\n")
                event("phase_end", phase=phase, exit_code=code)
                if code:
                    raise RuntimeError(f"{phase} failed")
        stop_our_daemon()
        if subprocess.run(["mountpoint", "-q", str(MOUNT)]).returncode == 0:
            raise RuntimeError("Daemon teardown left the experiment mount active")
        if driver() is not None:
            raise RuntimeError("Tutti owner teardown did not unbind cb")
        sysfs_driver_write("nvme", "bind")
        deadline = time.monotonic() + 15
        while True:
            try:
                device = block_for_bdf("nvme"); break
            except RuntimeError:
                if time.monotonic() > deadline: raise
                time.sleep(.1)
        check_uuid(device)
        command(["sudo", "-n", "mount", "-t", "ext4", "-o", "data=ordered", device, str(MOUNT)])
        mounted = True
        event("gds_device_mounted", device=device, uuid=UUID)
        config = json.loads((ROOT / "configs/cufile.json").read_text())
        config["logging"]["dir"] = str(run / "logs")
        (run / "cufile-A2.json").write_text(json.dumps(config, indent=2))
        with (run / "logs/A2.log").open("x") as log:
            event("phase_start", phase="A2", device=device)
            child = subprocess.Popen([str(ROOT / "build/gds_bench"), str(data), str(run / "trace.bin"), str(run / "raw-A2.csv")],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, CUFILE_ENV_PATH_JSON=str(run / "cufile-A2.json")))
            code = child.wait(timeout=600); child = None
            log.write(f"\nEXIT: {code}\n")
            event("phase_end", phase="A2", exit_code=code)
            if code: raise RuntimeError("A2 failed")
        h = hashlib.sha256()
        with data.open("rb") as f:
            for chunk in iter(lambda: f.read(8 << 20), b""): h.update(chunk)
        if h.hexdigest() != meta["data_sha256"]:
            raise RuntimeError("Post-run data hash mismatch")
        event("data_sha256_verified", sha256=h.hexdigest())
    finally:
        # Release only this experiment's resources. Never unload modules.
        if child is not None and child.poll() is None:
            command(["sudo", "-n", "kill", "-TERM", "--", f"-{child.pid}"])
            child.wait(timeout=30)
        if mounted:
            command(["sudo", "-n", "umount", str(MOUNT)])
        stop_our_daemon()
        if touched and driver() == "nvme":
            device = block_for_bdf("nvme")
            unmounted_device(device)
            sysfs_driver_write("nvme", "unbind")
        event("resources_released", final_driver=driver())


if __name__ == "__main__":
    main()
