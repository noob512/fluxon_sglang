#!/usr/bin/env python3
"""Fail closed when a foreign process enters any selected GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


SCHEMA = "mooncake_target_gpu_pid_observer_v1"
STOP = threading.Event()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_cmdline(pid: int) -> tuple[str, ...] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    return tuple(
        part.decode("utf-8", errors="replace")
        for part in raw.split(b"\0")
        if part
    )


def read_ppid(pid: int) -> int | None:
    try:
        lines = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    for line in lines.splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def read_starttime(pid: int) -> int | None:
    """Read /proc starttime (field 22) without trusting a reusable PID alone."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields_from_state = raw[close + 2 :].split()
    try:
        return int(fields_from_state[19])
    except (IndexError, ValueError):
        return None


def process_chain(
    pid: int,
    *,
    cmdline_reader: Callable[[int], tuple[str, ...] | None] = read_cmdline,
    ppid_reader: Callable[[int], int | None] = read_ppid,
    limit: int = 64,
) -> list[dict[str, object]]:
    chain: list[dict[str, object]] = []
    seen: set[int] = set()
    while pid > 0 and pid not in seen and len(chain) < limit:
        seen.add(pid)
        argv = cmdline_reader(pid)
        chain.append({"pid": pid, "argv": list(argv) if argv else []})
        parent = ppid_reader(pid)
        if parent is None or parent == pid:
            break
        pid = parent
    return chain


def chain_has_token(chain: Sequence[dict[str, object]], token: str) -> bool:
    return any(
        token in argument
        for item in chain
        for argument in item.get("argv", [])
        if isinstance(argument, str)
    )


def parse_gpu_inventory(text: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 2:
            raise ValueError(f"invalid GPU inventory row: {raw_line!r}")
        index = int(fields[0])
        if index in result:
            raise ValueError(f"duplicate GPU index: {index}")
        result[index] = fields[1]
    return result


def parse_compute_apps(text: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3:
            raise ValueError(f"invalid compute-app row: {raw_line!r}")
        result.append(
            {"gpu_uuid": fields[0], "pid": int(fields[1]), "used_memory": fields[2]}
        )
    return result


def foreign_processes(
    observations: Iterable[dict[str, object]],
    target_uuids: set[str],
    allowed_token: str,
    *,
    chain_reader: Callable[[int], list[dict[str, object]]] = process_chain,
    starttime_reader: Callable[[int], int | None] = read_starttime,
    allowed_identities: dict[int, int | None] | None = None,
) -> list[dict[str, object]]:
    if allowed_identities is None:
        allowed_identities = {}
    violations: list[dict[str, object]] = []
    for observation in observations:
        gpu_uuid = str(observation["gpu_uuid"])
        if gpu_uuid not in target_uuids:
            continue
        pid = int(observation["pid"])
        chain = chain_reader(pid)
        starttime = starttime_reader(pid)
        if chain_has_token(chain, allowed_token):
            allowed_identities[pid] = starttime
            continue
        if pid in allowed_identities:
            known_starttime = allowed_identities[pid]
            if starttime is None or known_starttime is None or starttime == known_starttime:
                # nvidia-smi can retain a dying CUDA PID after /proc/cmdline is
                # empty and PPid has become 1.  Preserve the prior
                # generation-safe admission; a reused PID has a new starttime.
                continue
        violations.append(
            {
                **observation,
                "process_starttime": starttime,
                "previously_allowed_starttime": allowed_identities.get(pid),
                "process_chain": chain,
            }
        )
    return sorted(
        violations, key=lambda item: (str(item["gpu_uuid"]), int(item["pid"]))
    )


def run_probe(command: Sequence[str], timeout_s: float) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"probe failed rc={completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.stdout


def write_invalid_marker(path: Path, event: dict[str, object]) -> None:
    payload = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-index", type=int, action="append", required=True)
    parser.add_argument("--allowed-ancestor-token", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--invalid-marker", type=Path, required=True)
    parser.add_argument("--watch-pid", type=int, required=True)
    parser.add_argument("--interval-s", type=float, default=0.5)
    parser.add_argument("--heartbeat-s", type=float, default=5.0)
    parser.add_argument("--probe-timeout-s", type=float, default=5.0)
    args = parser.parse_args(argv)
    if len(args.gpu_index) != len(set(args.gpu_index)) or any(
        index < 0 for index in args.gpu_index
    ):
        parser.error("GPU indices must be unique non-negative integers")
    if not args.allowed_ancestor_token:
        parser.error("allowed ancestor token must be non-empty")
    if args.watch_pid <= 0:
        parser.error("watch PID must be positive")
    if args.interval_s <= 0 or args.heartbeat_s <= 0 or args.probe_timeout_s <= 0:
        parser.error("intervals and timeout must be positive")
    return args


def request_stop(_signum: int, _frame: object) -> None:
    STOP.set()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists() or args.invalid_marker.exists():
        raise SystemExit("observer output or invalid marker already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.invalid_marker.parent.mkdir(parents=True, exist_ok=True)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, request_stop)

    script_path = Path(__file__).resolve()
    inventory = parse_gpu_inventory(
        run_probe(
            ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"],
            args.probe_timeout_s,
        )
    )
    missing = sorted(set(args.gpu_index) - set(inventory))
    if missing:
        raise SystemExit(f"GPU indices missing from inventory: {missing}")
    target_uuids = {inventory[index] for index in args.gpu_index}

    started = time.monotonic()
    samples = 0
    violations = 0
    last_heartbeat = float("-inf")
    allowed_identities: dict[int, int | None] = {}
    with args.output.open("x", encoding="utf-8", buffering=1) as handle:
        header = {
            "schema": SCHEMA,
            "event": "start",
            "timestamp_utc": utc_now(),
            "observer_pid": os.getpid(),
            "watch_pid": args.watch_pid,
            "gpu_indices": args.gpu_index,
            "gpu_uuids": sorted(target_uuids),
            "allowed_ancestor_token": args.allowed_ancestor_token,
            "interval_s": args.interval_s,
            "probe_timeout_s": args.probe_timeout_s,
            "script_path": str(script_path),
            "script_sha256": sha256_file(script_path),
        }
        handle.write(json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

        while not STOP.is_set() and Path(f"/proc/{args.watch_pid}").exists():
            elapsed = time.monotonic() - started
            try:
                observations = parse_compute_apps(
                    run_probe(
                        [
                            "nvidia-smi",
                            "--query-compute-apps=gpu_uuid,pid,used_memory",
                            "--format=csv,noheader,nounits",
                        ],
                        args.probe_timeout_s,
                    )
                )
                hits = foreign_processes(
                    observations,
                    target_uuids,
                    args.allowed_ancestor_token,
                    allowed_identities=allowed_identities,
                )
                error = None
            except Exception as exc:  # fail closed on driver/probe/parser errors
                hits = []
                error = f"{type(exc).__name__}: {exc}"
            samples += 1
            if hits or error is not None:
                violations += 1
            if hits or error is not None or elapsed - last_heartbeat >= args.heartbeat_s:
                event = {
                    "schema": SCHEMA,
                    "event": "violation" if hits or error is not None else "heartbeat",
                    "timestamp_utc": utc_now(),
                    "elapsed_s": elapsed,
                    "sample": samples,
                    "foreign_processes": hits,
                    "probe_error": error,
                }
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                if hits or error is not None:
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
            "watch_pid_exists": Path(f"/proc/{args.watch_pid}").exists(),
            "invalid_marker_exists": args.invalid_marker.exists(),
        }
        handle.write(json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return 2 if args.invalid_marker.exists() else 0


if __name__ == "__main__":
    raise SystemExit(main())
