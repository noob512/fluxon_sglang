#!/usr/bin/env python3
"""Record forbidden experiment interference for the complete request window."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


SCHEMA = "mooncake_interference_observer_v1"
STOP = threading.Event()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_cmdline(pid_dir: Path) -> tuple[str, ...] | None:
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    return tuple(
        item.decode("utf-8", errors="replace") for item in raw.split(b"\0") if item
    )


def read_ppid(pid: int) -> int | None:
    try:
        lines = Path(f"/proc/{pid}/status").read_text()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    for line in lines.splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def ancestor_pids(pid: int) -> set[int]:
    result: set[int] = set()
    while pid > 0 and pid not in result:
        result.add(pid)
        parent = read_ppid(pid)
        if parent is None or parent == pid:
            break
        pid = parent
    return result


def has_arg_pair(argv: Sequence[str], name: str, value: str) -> bool:
    return any(
        argv[index] == name and index + 1 < len(argv) and argv[index + 1] == value
        for index in range(len(argv))
    )


def invocation_target(argv: Sequence[str]) -> tuple[str, str, int]:
    """Return (kind, target, argv index) without inspecting payload arguments."""
    if not argv:
        return ("none", "", -1)
    executable = Path(argv[0]).name
    if executable.startswith("python"):
        index = 1
        while index < len(argv):
            arg = argv[index]
            if arg == "-m" and index + 1 < len(argv):
                return ("module", argv[index + 1], index + 1)
            if arg in ("-c", "-"):
                return ("python_code", arg, index)
            if arg in ("-W", "-X"):
                index += 2
                continue
            if arg.startswith("-"):
                index += 1
                continue
            return ("script", arg, index)
        return ("interpreter", argv[0], 0)
    if executable in ("bash", "dash", "sh", "zsh"):
        index = 1
        while index < len(argv):
            arg = argv[index]
            if arg == "-c":
                return ("shell_code", arg, index)
            if arg.startswith("-"):
                index += 1
                continue
            return ("script", arg, index)
        return ("interpreter", argv[0], 0)
    return ("executable", argv[0], 0)


def has_path_component(path: str, component: str) -> bool:
    return component in Path(path).parts


def classify(
    argv: Sequence[str],
    role: str,
    expected_model: str,
    expected_ports: Sequence[int],
    managed_load_paused: bool = False,
    engine: str = "sglang",
) -> str | None:
    kind, target, target_index = invocation_target(argv)
    target_name = Path(target).name
    action_args = argv[target_index + 1 :] if target_index >= 0 else ()
    if target_name == "inference_like_compute.py":
        return "inference_like_compute"
    if target_name == "gpu_idle_guard.py":
        return "gpu_idle_guard"
    if has_path_component(target, "fluxon_s3_benchmark"):
        return "fluxon_s3_benchmark"
    if target_name.startswith((".gpu_burn_script_", ".gpu_burn_cuda_")):
        return "gpu_burn_worker"
    if target_name == "gpu_burner.sh" and any(
        action in action_args for action in ("start", "watchdog")
    ):
        if not managed_load_paused:
            return "gpu_burn_manager"
    if target_name == "gpu_util_monitor_30m.sh":
        if any(action in action_args for action in ("start", "run")):
            return "gpu_util_monitor"
        if "once" in action_args and not managed_load_paused:
            return "gpu_util_monitor"
    if "vlcache" in target_name.lower() or any(
        part.lower() == "vlcache" for part in Path(target).parts
    ):
        return "external_vlcache"
    is_sglang_server = kind == "module" and target == "sglang.launch_server"
    if is_sglang_server:
        allowed = role == "gpu" and engine == "sglang" and (
            has_arg_pair(argv, "--model-path", expected_model)
            and any(
                has_arg_pair(argv, "--port", str(port)) for port in expected_ports
            )
            and has_arg_pair(argv, "--tensor-parallel-size", "2")
        )
        if not allowed:
            return "external_sglang"
    is_vllm_server = (
        kind == "module" and target.startswith("vllm.entrypoints.")
    ) or target_name in {"vllm", "vllm-server"}
    if is_vllm_server:
        model_is_positional = any(
            argv[index] == "serve"
            and index + 1 < len(argv)
            and argv[index + 1] == expected_model
            for index in range(len(argv))
        )
        model_matches = model_is_positional or has_arg_pair(
            argv, "--model", expected_model
        )
        allowed = role == "gpu" and engine == "vllm" and (
            model_matches
            and any(
                has_arg_pair(argv, "--port", str(port)) for port in expected_ports
            )
            and has_arg_pair(argv, "--tensor-parallel-size", "2")
        )
        if not allowed:
            return "external_vllm"
    return None


def scan_processes(
    role: str,
    expected_model: str,
    expected_ports: Sequence[int],
    ignored_pids: set[int] | None = None,
    monitor_pause_marker: Path | None = None,
    engine: str = "sglang",
) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    managed_load_paused = False
    if monitor_pause_marker is not None:
        managed_load_paused = monitor_pause_marker.is_file()
        if not managed_load_paused:
            hits.append(
                {
                    "pid": 0,
                    "reason": "monitor_pause_marker_missing",
                    "argv": [str(monitor_pause_marker)],
                }
            )
    if ignored_pids is None:
        ignored_pids = ancestor_pids(os.getpid())
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit() or int(pid_dir.name) in ignored_pids:
            continue
        argv = read_cmdline(pid_dir)
        if not argv:
            continue
        reason = classify(
            argv,
            role,
            expected_model,
            expected_ports,
            managed_load_paused=managed_load_paused,
            engine=engine,
        )
        if reason is not None:
            hits.append(
                {
                    "pid": int(pid_dir.name),
                    "reason": reason,
                    "argv": list(argv),
                }
            )
    return sorted(hits, key=lambda item: int(item["pid"]))


def write_invalid_marker(path: Path, event: dict[str, object]) -> None:
    encoded = (
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("gpu", "cpu"), required=True)
    parser.add_argument("--engine", choices=("sglang", "vllm"), default="sglang")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--invalid-marker", type=Path, required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument(
        "--expected-port",
        type=int,
        action="append",
        dest="expected_ports",
        help="allowed SGLang port; repeat once per TP2 instance",
    )
    parser.add_argument("--monitor-pause-marker", type=Path)
    parser.add_argument("--interval-s", type=float, default=1.0)
    parser.add_argument("--heartbeat-s", type=float, default=5.0)
    parser.add_argument("--duration-s", type=float, default=0.0)
    args = parser.parse_args(argv)
    if args.interval_s <= 0 or args.heartbeat_s <= 0 or args.duration_s < 0:
        parser.error("interval/heartbeat must be positive and duration non-negative")
    if args.expected_ports is None:
        args.expected_ports = [31001, 31002]
    if len(args.expected_ports) != len(set(args.expected_ports)) or any(
        port <= 0 or port > 65535 for port in args.expected_ports
    ):
        parser.error("expected ports must be unique values in 1..65535")
    return args


def request_stop(_signum: int, _frame: object) -> None:
    STOP.set()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() or args.invalid_marker.exists():
        raise SystemExit("observer output or invalid marker already exists")
    if (
        args.monitor_pause_marker is not None
        and not args.monitor_pause_marker.is_file()
    ):
        raise SystemExit(
            f"monitor pause marker is not a file: {args.monitor_pause_marker}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.invalid_marker.parent.mkdir(parents=True, exist_ok=True)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, request_stop)

    script_path = Path(__file__).resolve()
    started = time.monotonic()
    ignored_pids = ancestor_pids(os.getpid())
    samples = 0
    violations = 0
    last_heartbeat = float("-inf")
    with args.output.open("x", encoding="utf-8", buffering=1) as handle:
        header = {
            "schema": SCHEMA,
            "event": "start",
            "timestamp_utc": utc_now(),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "role": args.role,
            "engine": args.engine,
            "expected_model": args.expected_model,
            "expected_ports": args.expected_ports,
            "monitor_pause_marker": (
                str(args.monitor_pause_marker)
                if args.monitor_pause_marker is not None
                else None
            ),
            "interval_s": args.interval_s,
            "heartbeat_s": args.heartbeat_s,
            "duration_s": args.duration_s,
            "script_path": str(script_path),
            "script_sha256": sha256_file(script_path),
        }
        handle.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

        while not STOP.is_set():
            elapsed = time.monotonic() - started
            if args.duration_s and elapsed >= args.duration_s:
                break
            hits = scan_processes(
                args.role,
                args.expected_model,
                args.expected_ports,
                ignored_pids=ignored_pids,
                monitor_pause_marker=args.monitor_pause_marker,
                engine=args.engine,
            )
            samples += 1
            if hits:
                violations += 1
            if hits or elapsed - last_heartbeat >= args.heartbeat_s:
                event = {
                    "schema": SCHEMA,
                    "event": "violation" if hits else "heartbeat",
                    "timestamp_utc": utc_now(),
                    "elapsed_s": elapsed,
                    "sample": samples,
                    "hits": hits,
                }
                handle.write(
                    json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
                if hits:
                    write_invalid_marker(args.invalid_marker, event)
                last_heartbeat = elapsed
            STOP.wait(args.interval_s)

        summary = {
            "schema": SCHEMA,
            "event": "stop",
            "timestamp_utc": utc_now(),
            "elapsed_s": time.monotonic() - started,
            "samples": samples,
            "violations": violations,
            "invalid_marker_exists": args.invalid_marker.exists(),
        }
        handle.write(json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return 2 if args.invalid_marker.exists() else 0


if __name__ == "__main__":
    raise SystemExit(main())
