#!/usr/bin/env python3
"""Inject the run-scoped Fluxon kernel loader before SGL kernel imports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_SOURCE_SHA256 = (
    "9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4"
)
ANCHOR = "import torch\n\n"
REPLACEMENT = (
    "import torch\n\n"
    "from fluxon_sgl_kernel_loader import load_fluxon_sgl_kernel_ops\n\n"
    "load_fluxon_sgl_kernel_ops()\n\n"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transform(source: bytes) -> bytes:
    source_hash = hashlib.sha256(source).hexdigest()
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "sealed unified radix cache identity mismatch: "
            f"got={source_hash} expected={EXPECTED_SOURCE_SHA256}"
        )
    text = source.decode("utf-8")
    if text.count(ANCHOR) != 1:
        raise ValueError("kernel loader anchor must occur exactly once")
    output = text.replace(ANCHOR, REPLACEMENT, 1).encode("utf-8")
    if output.count(b"load_fluxon_sgl_kernel_ops()") != 1:
        raise AssertionError("kernel loader injection count mismatch")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_bytes()
    output = transform(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    value = {
        "schema_version": 1,
        "source": str(args.source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output": str(args.output),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "loader_call_count": output.count(b"load_fluxon_sgl_kernel_ops()"),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
