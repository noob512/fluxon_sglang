#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


BASELINE_SHA256 = "300a259711dc869df356a41b4c1c632b5b599cf7d596f4a11ac0783a1eaee33d"
CANDIDATE_SHA256 = "e41f194069cde9e01447a77688e0815ad5e522aae8f9ebe31ac59695e6580e2c"


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
    required = (
        "self.kv_anchor_node = kv_anchor_node",
        "def _acquire_fluxon_hostless_anchor_lock(",
        "def _release_fluxon_hostless_anchor_lock(",
        "self._release_fluxon_hostless_anchor_lock(operation)",
        '"Fluxon hostless anchor lock Snapshot:',
        '"prefetch_device_anchor_lock_error"',
    )
    for marker in required:
        if source.count(marker) != 1:
            raise AssertionError(f"expected one marker {marker!r}")

    tree = ast.parse(source, filename=str(args.candidate))
    compile(tree, str(args.candidate), "exec")
    print(f"e44 r118 ready-anchor lock validation: passed sha256={actual_candidate}")


if __name__ == "__main__":
    main()
