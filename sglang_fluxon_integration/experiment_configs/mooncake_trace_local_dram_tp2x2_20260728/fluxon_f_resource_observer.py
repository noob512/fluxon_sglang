#!/usr/bin/env python3
"""Continuously validate Fluxon group-F resource and identity gates."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


STOP = threading.Event()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def memory_events() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in read_text(Path("/sys/fs/cgroup/memory.events")).splitlines():
        name, value = line.split()
        result[name] = int(value)
    return result


def pid_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def pid_exe(pid: int) -> str:
    try:
        return str(Path(f"/proc/{pid}/exe").resolve())
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return ""


def pid_parent(pid: int) -> int:
    try:
        lines = Path(f"/proc/{pid}/status").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return 0
    for line in lines:
        if line.startswith("PPid:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def pid_belongs_to_runtime(
    pid: int, runtime_prefix: str, runtime_marker: str, max_depth: int = 8
) -> bool:
    """Accept renamed workers only when a bounded ancestor names this run."""
    current = int(pid)
    seen: set[int] = set()
    for _ in range(max_depth + 1):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        exe = pid_exe(current)
        argv = pid_cmdline(current)
        command = "\0".join(argv)
        if (
            exe.startswith(runtime_prefix)
            or any(item.startswith(runtime_prefix) for item in argv)
            or runtime_marker in command
        ):
            return True
        current = pid_parent(current)
    return False


def process_rows() -> list[tuple[int, list[str]]]:
    rows: list[tuple[int, list[str]]] = []
    for item in Path("/proc").iterdir():
        if item.name.isdigit():
            argv = pid_cmdline(int(item.name))
            if argv:
                rows.append((int(item.name), argv))
    return rows


def run_checked(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Keep probes outside the observer's foreground signal group."""
    return subprocess.run(
        list(command),
        check=True,
        text=True,
        capture_output=True,
        start_new_session=True,
    )


def listening_ports() -> set[int]:
    result = run_checked(["ss", "-ltnH"])
    ports: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        endpoint = fields[3]
        try:
            ports.add(int(endpoint.rsplit(":", 1)[1]))
        except (ValueError, IndexError):
            continue
    return ports


def missing_listening_ports(required_ports: Sequence[int]) -> list[int]:
    if not required_ports:
        return []
    return sorted(set(required_ports) - listening_ports())


def gpu_processes() -> list[dict[str, object]]:
    uuid_result = run_checked(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid",
            "--format=csv,noheader,nounits",
        ]
    )
    uuid_to_index: dict[str, int] = {}
    for line in uuid_result.stdout.splitlines():
        index, uuid = [part.strip() for part in line.split(",", 1)]
        uuid_to_index[uuid] = int(index)
    app_result = run_checked(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    rows: list[dict[str, object]] = []
    for line in app_result.stdout.splitlines():
        if not line.strip():
            continue
        uuid, pid, name, used = [part.strip() for part in line.split(",", 3)]
        numeric_pid = int(pid)
        rows.append(
            {
                "gpu": uuid_to_index[uuid],
                "pid": numeric_pid,
                "ppid": pid_parent(numeric_pid),
                "name": name,
                "used_mib": int(used),
                "exe": pid_exe(numeric_pid),
                "argv": pid_cmdline(numeric_pid),
            }
        )
    return sorted(rows, key=lambda row: (int(row["gpu"]), int(row["pid"])))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("gpu", "cpu"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--invalid-marker", type=Path, required=True)
    parser.add_argument("--expected-hostname", required=True)
    parser.add_argument("--expected-ip", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--hca", action="append", required=True)
    parser.add_argument("--required-port", action="append", type=int, default=[])
    parser.add_argument("--required-process", action="append", default=[])
    parser.add_argument("--monitor-pause-marker", type=Path)
    parser.add_argument("--interval-s", type=float, default=1.0)
    parser.add_argument("--heartbeat-s", type=float, default=5.0)
    parser.add_argument("--duration-s", type=float, default=0.0)
    args = parser.parse_args(argv)
    if args.interval_s <= 0 or args.heartbeat_s <= 0 or args.duration_s < 0:
        parser.error("invalid observer interval/duration")
    if len(set(args.hca)) != len(args.hca):
        parser.error("duplicate HCA")
    if len(set(args.required_port)) != len(args.required_port):
        parser.error("duplicate required port")
    return args


def write_invalid(path: Path, event: dict[str, object]) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(event, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def signal_stop(_signum: int, _frame: object) -> None:
    STOP.set()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() or args.invalid_marker.exists():
        raise SystemExit("observer output or invalid marker already exists")
    if args.role == "gpu" and args.monitor_pause_marker is None:
        raise SystemExit("GPU observer requires --monitor-pause-marker")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.invalid_marker.parent.mkdir(parents=True, exist_ok=True)
    baseline_events = memory_events()
    pid1_start = Path("/proc/1/stat").read_text().split()[21]
    started = time.monotonic()
    last_heartbeat = float("-inf")
    samples = violations = 0
    runtime_prefix = str(args.runtime_root.resolve()) + "/"
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, signal_stop)

    with args.output.open("x", encoding="utf-8", buffering=1) as stream:
        start = {
            "event": "start",
            "timestamp_utc": now(),
            "role": args.role,
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "pid1_start_ticks": pid1_start,
            "memory_events": baseline_events,
            "runtime_root": str(args.runtime_root),
            "hcas": args.hca,
            "required_ports": args.required_port,
            "required_processes": args.required_process,
        }
        stream.write(json.dumps(start, sort_keys=True) + "\n")
        while not STOP.is_set():
            elapsed = time.monotonic() - started
            if args.duration_s and elapsed >= args.duration_s:
                break
            problems: list[dict[str, object]] = []
            if socket.gethostname() != args.expected_hostname:
                problems.append({"reason": "hostname_changed", "actual": socket.gethostname()})
            ips = run_checked(["hostname", "-I"]).stdout.split()
            if args.expected_ip not in ips:
                problems.append({"reason": "ip_missing", "actual": ips})
            if Path("/proc/1/stat").read_text().split()[21] != pid1_start:
                problems.append({"reason": "pid1_restarted"})
            current_events = memory_events()
            for key in ("oom", "oom_kill"):
                if current_events.get(key, 0) != baseline_events.get(key, 0):
                    problems.append(
                        {
                            "reason": f"memory_{key}_changed",
                            "before": baseline_events.get(key, 0),
                            "after": current_events.get(key, 0),
                        }
                    )
            for hca in args.hca:
                state_path = Path(f"/sys/class/infiniband/{hca}/ports/1/state")
                state = read_text(state_path) if state_path.is_file() else "missing"
                if "ACTIVE" not in state:
                    problems.append({"reason": "hca_not_active", "hca": hca, "state": state})
            if args.monitor_pause_marker is not None and not args.monitor_pause_marker.is_file():
                problems.append({"reason": "pause_marker_missing"})
            missing_ports = missing_listening_ports(args.required_port)
            if missing_ports:
                problems.append({"reason": "required_ports_missing", "ports": missing_ports})
            processes = process_rows()
            joined = [(pid, "\0".join(cmdline)) for pid, cmdline in processes]
            for marker in args.required_process:
                if not any(marker in command for _pid, command in joined):
                    problems.append({"reason": "required_process_missing", "marker": marker})
            gpus = gpu_processes()
            if args.role == "gpu":
                for row in gpus:
                    gpu = int(row["gpu"])
                    belongs_to_runtime = pid_belongs_to_runtime(
                        int(row["pid"]),
                        runtime_prefix,
                        str(args.runtime_root),
                    )
                    if gpu >= 4:
                        problems.append({"reason": "unused_gpu_busy", "process": row})
                    elif not belongs_to_runtime:
                        problems.append({"reason": "foreign_process_on_gpu0_3", "process": row})
            else:
                for row in gpus:
                    if pid_belongs_to_runtime(
                        int(row["pid"]),
                        runtime_prefix,
                        str(args.runtime_root),
                    ):
                        problems.append({"reason": "f_process_created_cpu_gpu_context", "process": row})

            samples += 1
            if problems:
                violations += len(problems)
                event = {
                    "event": "violation",
                    "timestamp_utc": now(),
                    "elapsed_s": elapsed,
                    "problems": problems,
                }
                stream.write(json.dumps(event, sort_keys=True) + "\n")
                write_invalid(args.invalid_marker, event)
            if problems or elapsed - last_heartbeat >= args.heartbeat_s:
                heartbeat = {
                    "event": "heartbeat",
                    "timestamp_utc": now(),
                    "elapsed_s": elapsed,
                    "samples": samples,
                    "violations": violations,
                    "memory_current": int(read_text(Path("/sys/fs/cgroup/memory.current"))),
                    "gpu_processes": gpus,
                }
                stream.write(json.dumps(heartbeat, sort_keys=True) + "\n")
                last_heartbeat = elapsed
            STOP.wait(args.interval_s)
        stop = {
            "event": "stop",
            "timestamp_utc": now(),
            "elapsed_s": time.monotonic() - started,
            "samples": samples,
            "violations": violations,
            "invalid": args.invalid_marker.exists(),
        }
        stream.write(json.dumps(stop, sort_keys=True) + "\n")
    return 1 if args.invalid_marker.exists() else 0


if __name__ == "__main__":
    raise SystemExit(main())
