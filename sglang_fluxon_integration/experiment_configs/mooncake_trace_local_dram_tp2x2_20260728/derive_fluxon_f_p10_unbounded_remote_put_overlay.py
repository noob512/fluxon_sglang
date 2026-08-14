#!/usr/bin/env python3
"""Derive a p10 launcher that removes both owner remote-Put limits.

The p9 launcher is otherwise preserved byte-for-byte: common two-rail PPLX,
layer-batch background H2D, GPU4-7 placement, capacity, model, and trace do not
change.  Omitting both environment variables makes the existing Rust runtime
construct ``OwnerRemotePutAdmission`` with ``max_bytes=None`` and
``max_items=None``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


EXPECTED_P9_WRAPPER_SHA256 = (
    "bdb4b1188b73f7ec59b6575d6578548a9f243e68465ea366fef6e9bb922a3094"
)
EXPECTED_P9_INNER_SHA256 = (
    "4f51091847b12584f180e972053fd4ff8dfbecdfb8aab709ff2700256811c924"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_exact(text: str, old: str, new: str, expected_count: int = 1) -> str:
    actual_count = text.count(old)
    if actual_count != expected_count:
        raise ValueError(
            f"expected {expected_count} occurrence(s), found {actual_count}: {old!r}"
        )
    return text.replace(old, new)


def derive_wrapper(text: str) -> str:
    text = replace_exact(
        text,
        "  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES=17179869184\n"
        "  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS=4096\n",
        "",
    )
    text = replace_exact(
        text,
        '  echo "pplx_rails local=2 remote=2 devices=mlx5_0,mlx5_1"\n',
        '  echo "pplx_rails local=2 remote=2 devices=mlx5_0,mlx5_1"\n'
        '  echo "remote_put_admission bytes=unbounded items=unbounded"\n',
    )
    return text


def write_new(path: Path, payload: str, mode: int) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    os.chmod(path, mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p9-wrapper-source", type=Path, required=True)
    parser.add_argument("--p9-inner-source", type=Path, required=True)
    parser.add_argument("--wrapper-output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    source_sha256 = {
        "p9_wrapper": sha256(args.p9_wrapper_source),
        "p9_inner": sha256(args.p9_inner_source),
    }
    expected = {
        "p9_wrapper": EXPECTED_P9_WRAPPER_SHA256,
        "p9_inner": EXPECTED_P9_INNER_SHA256,
    }
    if source_sha256 != expected:
        raise SystemExit(
            "p9 launcher identity mismatch: "
            f"actual={source_sha256!r} expected={expected!r}"
        )

    try:
        wrapper = derive_wrapper(args.p9_wrapper_source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"refusing p10 derivation: {exc}") from exc

    write_new(args.wrapper_output, wrapper, 0o555)
    manifest = {
        "schema": "fluxon_f_p10_unbounded_remote_put_overlay_v1",
        "source_sha256": source_sha256,
        "output_sha256": {"wrapper": sha256(args.wrapper_output)},
        "owner_remote_put_admission": {
            "max_inflight_bytes": None,
            "max_inflight_items": None,
            "scope": "gpu_local_owner_only",
        },
        "unchanged": [
            "p9 common two-rail PPLX",
            "p8 layer-batch background H2D",
            "local and remote DRAM capacity",
            "remote CPU owner configuration",
            "GDR and SSD disabled",
            "model, TP, GPU mapping, router, and trace",
        ],
    }
    write_new(
        args.manifest,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        0o444,
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
