#!/usr/bin/env python3
"""Create a fail-closed measured capacity manifest for one formal run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


SCHEMA = "mooncake_local_dram_capacity_v2"
LOCAL_TOTAL_BYTES = 274_877_906_944
REMOTE_SEGMENT_BYTES = 274_877_906_944
PAGE_BYTES = 4_718_592
EXPECTED_HICACHE_GB = {"A": 16, "B": 32, "C": 48, "D": 0}
EXPECTED_HICACHE_RATIO = {"A": 2.0, "B": 2.0, "C": 2.0, "D": 4.65984}
EXPECTED_ALLOCATION_GB = {"A": 16.00, "B": 32.00, "C": 48.00, "D": 68.72}
EXPECTED_ALIGNMENT_SLACK_BYTES = {"A": 0, "B": 0, "C": 0, "D": 10_485_760}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("A", "B", "C", "D"), required=True)
    parser.add_argument("--hicache-size-gb", type=int, required=True)
    parser.add_argument("--hicache-ratio", type=float)
    parser.add_argument("--hicache-rank-bytes", type=int, nargs=4)
    parser.add_argument(
        "--mooncake-local-instance-segment-bytes",
        type=int,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument(
        "--mooncake-remote-segment-bytes",
        type=int,
        default=REMOTE_SEGMENT_BYTES,
    )
    parser.add_argument(
        "--sglang-log",
        type=Path,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument(
        "--metrics-file",
        type=Path,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--gpu-hostname", default=socket.gethostname())
    parser.add_argument("--gpu-private-ip", required=True)
    parser.add_argument(
        "--instance0-gpus",
        type=int,
        nargs=2,
        default=(0, 1),
        metavar=("GPU0", "GPU1"),
    )
    parser.add_argument(
        "--instance1-gpus",
        type=int,
        nargs=2,
        default=(2, 3),
        metavar=("GPU0", "GPU1"),
    )
    parser.add_argument("--remote-hostname", required=True)
    parser.add_argument("--remote-private-ip", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.hicache_size_gb != EXPECTED_HICACHE_GB[args.group]:
        raise SystemExit(
            f"hicache size mismatch for {args.group}: "
            f"expected={EXPECTED_HICACHE_GB[args.group]} actual={args.hicache_size_gb}"
        )
    gpu_placement = [*args.instance0_gpus, *args.instance1_gpus]
    if any(gpu < 0 for gpu in gpu_placement) or len(set(gpu_placement)) != 4:
        raise SystemExit(
            "the two TP2 instances require four distinct non-negative GPU indices: "
            f"instance0={args.instance0_gpus} instance1={args.instance1_gpus}"
        )
    expected_ratio = EXPECTED_HICACHE_RATIO[args.group]
    if args.hicache_ratio is None:
        args.hicache_ratio = expected_ratio
    if args.hicache_ratio != expected_ratio:
        raise SystemExit(
            f"hicache ratio mismatch for {args.group}: "
            f"expected={expected_ratio} actual={args.hicache_ratio}"
        )
    for evidence_path in (*args.sglang_log, *args.metrics_file):
        if not evidence_path.is_file():
            raise SystemExit(f"evidence file does not exist: {evidence_path}")

    allocation_marker = (
        f"Allocating {EXPECTED_ALLOCATION_GB[args.group]:.2f} GB host memory "
        "for hierarchical KV cache."
    )
    derived_rank_values: list[int] = []
    instance_evidence = []
    for instance_index, (log_path, metrics_path) in enumerate(
        zip(args.sglang_log, args.metrics_file, strict=True)
    ):
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        if "tp_size=2" not in log_text:
            raise SystemExit(
                f"instance{instance_index} SGLang log does not prove tp_size=2"
            )
        missing_ranks = [
            rank
            for rank in range(2)
            if not re.search(
                rf"\[[^\]\n]*\bTP{rank}\].*{re.escape(allocation_marker)}",
                log_text,
            )
        ]
        if missing_ranks:
            raise SystemExit(
                f"instance{instance_index} SGLang log lacks HiCache allocation "
                f"evidence for ranks {missing_ranks}"
            )

        metrics_text = metrics_path.read_text(encoding="utf-8", errors="replace")
        metric_values = re.findall(
            r'^sglang:hicache_host_total_tokens\{[^\n]*tp_rank="0"[^\n]*\}\s+([0-9]+(?:[.]0)?)$',
            metrics_text,
            flags=re.MULTILINE,
        )
        if len(metric_values) != 1:
            raise SystemExit(
                f"instance{instance_index} metrics must contain exactly one TP0 "
                "hicache_host_total_tokens sample"
            )
        rank_tokens_float = float(metric_values[0])
        rank_tokens = int(rank_tokens_float)
        if rank_tokens_float != rank_tokens or rank_tokens <= 0 or rank_tokens % 64 != 0:
            raise SystemExit(
                f"invalid instance{instance_index} HiCache rank token capacity: "
                f"{rank_tokens_float}"
            )
        derived_rank_bytes = rank_tokens * (PAGE_BYTES // 64)
        derived_rank_values.extend([derived_rank_bytes, derived_rank_bytes])
        instance_evidence.append(
            {
                "instance": f"instance{instance_index}",
                "ports": 31001 + instance_index,
                "sglang_log": {
                    "path": str(log_path.resolve()),
                    "sha256": sha256_file(log_path),
                    "bytes": log_path.stat().st_size,
                },
                "metrics": {
                    "path": str(metrics_path.resolve()),
                    "sha256": sha256_file(metrics_path),
                    "bytes": metrics_path.stat().st_size,
                    "hicache_host_total_tokens_per_rank": rank_tokens,
                },
            }
        )
    if args.hicache_rank_bytes is not None and args.hicache_rank_bytes != derived_rank_values:
        raise SystemExit(
            f"provided rank bytes {args.hicache_rank_bytes} do not match "
            f"metrics-derived {derived_rank_values}"
        )
    args.hicache_rank_bytes = derived_rank_values

    if any(value <= 0 or value % PAGE_BYTES != 0 for value in args.hicache_rank_bytes):
        raise SystemExit(
            f"each rank byte count must be a positive multiple of {PAGE_BYTES}"
        )

    hicache_total = sum(args.hicache_rank_bytes)
    instance_segments = args.mooncake_local_instance_segment_bytes
    if any(value < 0 for value in instance_segments):
        raise SystemExit("each instance Mooncake segment must be non-negative")
    if instance_segments[0] != instance_segments[1]:
        raise SystemExit(
            f"the two TP2 instance segments must be equal: {instance_segments}"
        )
    local_segment_total = sum(instance_segments)
    if args.group == "D" and instance_segments != [0, 0]:
        raise SystemExit("group D requires zero local Mooncake segments")
    if args.group != "D" and any(value == 0 for value in instance_segments):
        raise SystemExit(f"group {args.group} requires positive local Mooncake segments")
    local_payload = hicache_total + local_segment_total
    alignment_slack = EXPECTED_ALIGNMENT_SLACK_BYTES[args.group]
    local_sum = local_payload + alignment_slack
    if local_sum != LOCAL_TOTAL_BYTES:
        raise SystemExit(
            f"local capacity mismatch: hicache={hicache_total} "
            f"mooncake_instances={instance_segments} payload={local_payload} "
            f"alignment_slack={alignment_slack} sum={local_sum} "
            f"expected={LOCAL_TOTAL_BYTES}"
        )
    if args.mooncake_remote_segment_bytes != REMOTE_SEGMENT_BYTES:
        raise SystemExit(
            f"remote capacity mismatch: actual={args.mooncake_remote_segment_bytes} "
            f"expected={REMOTE_SEGMENT_BYTES}"
        )

    evidence = {"instances": instance_evidence}

    value = {
        "schema": SCHEMA,
        "status": "final_measured",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "group": args.group,
        "namespace": args.namespace,
        "hicache_size_gb_per_rank": args.hicache_size_gb,
        "hicache_ratio": args.hicache_ratio,
        "hicache_rank_bytes": args.hicache_rank_bytes,
        "hicache_total_bytes": hicache_total,
        "mooncake_local_instance_segment_bytes": instance_segments,
        "mooncake_local_segment_bytes": local_segment_total,
        "local_payload_bytes": local_payload,
        "page_alignment_slack_bytes": alignment_slack,
        "local_total_bytes": local_sum,
        "mooncake_remote_segment_bytes": args.mooncake_remote_segment_bytes,
        "page_bytes_per_rank": PAGE_BYTES,
        "topology": {
            "instance0": {
                "tp_size": 2,
                "gpus": list(args.instance0_gpus),
                "port": 31001,
            },
            "instance1": {
                "tp_size": 2,
                "gpus": list(args.instance1_gpus),
                "port": 31002,
            },
            "router_port": 32000,
            "router_worker_hosts": ["127.0.0.1", "127.0.0.1"],
        },
        "gpu": {
            "hostname": args.gpu_hostname,
            "private_ip": args.gpu_private_ip,
        },
        "remote_cpu": {
            "hostname": args.remote_hostname,
            "private_ip": args.remote_private_ip,
        },
        "capacity_evidence": evidence,
        "generator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
            "pid": os.getpid(),
        },
    }
    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    print(hashlib.sha256(encoded).hexdigest(), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
