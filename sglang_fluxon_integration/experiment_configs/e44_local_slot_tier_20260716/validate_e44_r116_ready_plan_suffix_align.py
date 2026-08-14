#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


BASELINE_SHA256 = "ba2f510c1fbbadfae4879cbbc5631b89eceeddbfc3841688d26597d6d4d182d4"
CANDIDATE_SHA256 = "300a259711dc869df356a41b4c1c632b5b599cf7d596f4a11ac0783a1eaee33d"


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
        "self.kv_plan_offset_pages = 0",
        "def _fluxon_hostless_ready_value_ptrs(",
        '"ambiguous_plan_suffix_alignment"',
        '"Fluxon ready restore suffix aligned:',
    )
    for marker in required:
        if source.count(marker) != 1:
            raise AssertionError(f"expected one marker {marker!r}")

    tree = ast.parse(source, filename=str(args.candidate))
    compile(tree, str(args.candidate), "exec")
    print(f"e44 r116 ready-plan suffix validation: passed sha256={actual_candidate}")


if __name__ == "__main__":
    main()
