#!/usr/bin/env python3
"""Low-overhead, node-local InfiniBand port counter sampler for E44 r28."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path


NUMBER_RE = re.compile(r"(-?\d+)")
STOP = threading.Event()


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_perfquery(stdout: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip().strip(".")
        match = NUMBER_RE.search(raw_value)
        if key and match:
            values[key] = int(match.group(1))
    return values


def port_metadata(hca: str, port: int) -> dict[str, object]:
    base = Path("/sys/class/infiniband") / hca / "ports" / str(port)
    rate = read_text(base / "rate")
    rate_match = NUMBER_RE.search(rate or "")
    return {
        "hca": hca,
        "port": port,
        "state": read_text(base / "state"),
        "phys_state": read_text(base / "phys_state"),
        "rate": rate,
        "rate_gbps": int(rate_match.group(1)) if rate_match else None,
        "link_layer": read_text(base / "link_layer"),
        "lid": read_text(base / "lid"),
        "sm_lid": read_text(base / "sm_lid"),
    }


def sample_hca(
    perfquery: Path,
    lib_dir: Path,
    hca: str,
    port: int,
    timeout_s: float,
) -> dict[str, object]:
    wall_start_ns = time.time_ns()
    mono_start_ns = time.monotonic_ns()
    env = os.environ.copy()
    old_ld_path = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = str(lib_dir) + (f":{old_ld_path}" if old_ld_path else "")
    try:
        completed = subprocess.run(
            [str(perfquery), "-x", "-C", hca, "-P", str(port)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        counters = parse_perfquery(completed.stdout) if completed.returncode == 0 else {}
        error = None
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or f"rc={completed.returncode}")[:1000]
    except Exception as exc:  # keep sampling the other HCA and subsequent intervals
        counters = {}
        error = f"{type(exc).__name__}: {exc}"[:1000]
    mono_end_ns = time.monotonic_ns()
    wall_end_ns = time.time_ns()
    return {
        "hca": hca,
        "port": port,
        "wall_start_ns": wall_start_ns,
        "wall_end_ns": wall_end_ns,
        "wall_mid_ns": (wall_start_ns + wall_end_ns) // 2,
        "monotonic_start_ns": mono_start_ns,
        "monotonic_end_ns": mono_end_ns,
        "query_duration_ms": (mono_end_ns - mono_start_ns) / 1e6,
        "counters": counters,
        "error": error,
    }


def handle_stop(_signum: int, _frame: object) -> None:
    STOP.set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--perfquery", required=True)
    parser.add_argument("--lib-dir", required=True)
    parser.add_argument("--hcas", default="mlx5_4,mlx5_6")
    parser.add_argument("--port", type=int, default=1)
    parser.add_argument("--interval-ms", type=float, default=500.0)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    args = parser.parse_args()

    if args.interval_ms <= 0:
        parser.error("--interval-ms must be positive")

    output = Path(args.output)
    perfquery = Path(args.perfquery)
    lib_dir = Path(args.lib_dir)
    hcas = [item.strip() for item in args.hcas.split(",") if item.strip()]
    if not perfquery.is_file():
        parser.error(f"perfquery not found: {perfquery}")
    if not hcas:
        parser.error("no HCA selected")

    output.parent.mkdir(parents=True, exist_ok=True)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, handle_stop)

    metadata = {
        "type": "metadata",
        "schema": "e44_hca_observer_v1",
        "node": args.node,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "started_wall_ns": time.time_ns(),
        "started_monotonic_ns": time.monotonic_ns(),
        "interval_ms": args.interval_ms,
        "perfquery": str(perfquery),
        "perfquery_sha256": sha256_file(perfquery),
        "lib_dir": str(lib_dir),
        "ports": [port_metadata(hca, args.port) for hca in hcas],
    }

    interval_ns = int(args.interval_ms * 1e6)
    next_tick_ns = time.monotonic_ns()
    sequence = 0
    with output.open("w", encoding="utf-8", buffering=1) as stream:
        stream.write(json.dumps(metadata, sort_keys=True) + "\n")
        while not STOP.is_set():
            cycle_wall_start_ns = time.time_ns()
            cycle_mono_start_ns = time.monotonic_ns()
            samples = [
                sample_hca(perfquery, lib_dir, hca, args.port, args.timeout_s)
                for hca in hcas
            ]
            cycle_mono_end_ns = time.monotonic_ns()
            record = {
                "type": "sample",
                "schema": "e44_hca_observer_v1",
                "node": args.node,
                "sequence": sequence,
                "cycle_wall_start_ns": cycle_wall_start_ns,
                "cycle_wall_end_ns": time.time_ns(),
                "cycle_monotonic_start_ns": cycle_mono_start_ns,
                "cycle_monotonic_end_ns": cycle_mono_end_ns,
                "cycle_duration_ms": (cycle_mono_end_ns - cycle_mono_start_ns) / 1e6,
                "hcas": samples,
            }
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            sequence += 1

            next_tick_ns += interval_ns
            now_ns = time.monotonic_ns()
            if next_tick_ns <= now_ns:
                skipped = ((now_ns - next_tick_ns) // interval_ns) + 1
                next_tick_ns += skipped * interval_ns
            STOP.wait(max(0.0, (next_tick_ns - time.monotonic_ns()) / 1e9))

        stream.write(
            json.dumps(
                {
                    "type": "stopped",
                    "schema": "e44_hca_observer_v1",
                    "node": args.node,
                    "sample_count": sequence,
                    "stopped_wall_ns": time.time_ns(),
                    "stopped_monotonic_ns": time.monotonic_ns(),
                },
                sort_keys=True,
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
