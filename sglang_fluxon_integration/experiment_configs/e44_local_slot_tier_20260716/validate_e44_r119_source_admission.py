#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


BASELINE_SHA256 = "e41f194069cde9e01447a77688e0815ad5e522aae8f9ebe31ac59695e6580e2c"
CANDIDATE_SHA256 = "9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    actual_baseline = sha256(args.baseline)
    if actual_baseline != BASELINE_SHA256:
        raise AssertionError(
            f"baseline SHA mismatch: expected={BASELINE_SHA256} actual={actual_baseline}"
        )
    actual_candidate = sha256(args.candidate)
    if actual_candidate != CANDIDATE_SHA256:
        raise AssertionError(
            f"candidate SHA mismatch: expected={CANDIDATE_SHA256} actual={actual_candidate}"
        )

    source = args.candidate.read_text(encoding="utf-8")
    required_once = (
        "_FLUXON_HOSTLESS_ADMISSION_TOTAL_TOKEN_LIMIT = 234_048",
        "_FLUXON_HOSTLESS_ADMISSION_REMOTE_PAGE_LIMIT = 512",
        "def _try_acquire_fluxon_hostless_prefetch_admission(",
        "def _release_fluxon_hostless_prefetch_admission(",
        '"Fluxon hostless source admission Snapshot:',
        'release_prefetch_admission("prefetch_plan_execute_error")',
        '"prefetch_ready",',
    )
    for marker in required_once:
        if source.count(marker) != 1:
            raise AssertionError(f"expected one marker {marker!r}")

    prefetch_start = source.index("    def prefetch_from_storage(")
    hostless_start = source.index(
        "        if self._is_fluxon_hostless_full_mode():", prefetch_start
    )
    generic_start = source.index(
        "\n        extra_key = last_host_node.key.extra_key", hostless_start + 1
    )
    hostless_source = source[hostless_start:generic_start]
    if ".prefetch_rate_limited()" in hostless_source:
        raise AssertionError("hostless path still calls the generic host-pool limiter")
    ordered_markers = (
        "kv_handle = backend.get_plan(",
        "self._try_acquire_fluxon_hostless_prefetch_admission(",
        "kv_handle = backend.execute_get_plan_cpu(",
    )
    positions = [hostless_source.index(marker) for marker in ordered_markers]
    if positions != sorted(positions):
        raise AssertionError(
            "source admission must happen after Plan and before transfer execution"
        )
    if "prefetch_tokens_occupied -= operation.total_tokens" in source:
        raise AssertionError("manual hostless debt release bypasses unified admission")

    tree = ast.parse(source, filename=str(args.candidate))
    compile(tree, str(args.candidate), "exec")
    print(f"e44 r119 source-aware admission validation: passed sha256={actual_candidate}")


if __name__ == "__main__":
    main()
