#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


BASELINE_SHA256 = "223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9"

OLD_BLOCK = '''                if ready_node is None:
                    if req.rid in self._fluxon_hostless_request_observations:
'''

NEW_BLOCK = '''                if ready_node is None:
                    stale_operation = self.fluxon_hostless_ready_prefetch.pop(req.rid)
                    assert stale_operation is ready_operation, (
                        "Fluxon ready-prefetch identity changed during one scheduler turn"
                    )
                    self._cancel_fluxon_hostless_prefetch_operation(
                        stale_operation,
                        "ready_no_whole_node_prefix",
                    )
                    if req.rid in self._fluxon_hostless_request_observations:
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    actual_baseline_sha = sha256(args.baseline)
    if actual_baseline_sha != BASELINE_SHA256:
        raise AssertionError(
            f"baseline SHA mismatch: expected={BASELINE_SHA256} actual={actual_baseline_sha}"
        )

    baseline = args.baseline.read_text(encoding="utf-8")
    candidate = args.candidate.read_text(encoding="utf-8")
    if baseline.count(OLD_BLOCK) != 1:
        raise AssertionError("baseline must contain exactly one target lifecycle branch")
    expected = baseline.replace(OLD_BLOCK, NEW_BLOCK, 1)
    if candidate != expected:
        raise AssertionError("candidate contains changes outside the exact holder-release block")

    tree = ast.parse(candidate, filename=str(args.candidate))
    compile(tree, str(args.candidate), "exec")
    print(f"e44 r114 ready-prefetch release validation: passed sha256={sha256(args.candidate)}")


if __name__ == "__main__":
    main()
