#!/usr/bin/env python3
"""Add the narrow StorageMetrics compatibility gate used by Fluxon F.

The sealed r54 adapter can export newer Fluxon L2/IO observations, while the
SGLang base selected for this experiment has the older four-list
``StorageMetrics`` type.  The transform leaves KV operations untouched and
skips only the observations that the old type cannot represent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


EXPECTED_SOURCE_SHA256 = (
    "eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd"
)

OLD = """    def _add_observability_delta(self, stats: StorageMetrics) -> None:
        if getattr(self, \"store\", None) is None:
"""

NEW = """    def _add_observability_delta(self, stats: StorageMetrics) -> None:
        # This sealed SGLang base predates Fluxon's L2/IO StorageMetrics
        # extensions.  Preserve the legacy page/bandwidth metrics returned by
        # get_stats(), but do not collect deltas that the type cannot express.
        if not callable(getattr(stats, \"add_l2_hit_sample\", None)) or not callable(
            getattr(stats, \"add_io_sample\", None)
        ):
            return
        if getattr(self, \"store\", None) is None:
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transform(text: str) -> str:
    count = text.count(OLD)
    if count != 1:
        raise ValueError(
            f"expected one r54 observability hook, found {count}; refusing transform"
        )
    if "StorageMetrics compatibility gate used by Fluxon F" in text:
        raise ValueError("input already contains the Fluxon F compatibility gate")
    return text.replace(OLD, NEW, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    source_hash = sha256(args.source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SystemExit(
            "sealed r54 adapter identity mismatch: "
            f"got={source_hash} expected={EXPECTED_SOURCE_SHA256}"
        )

    output_text = transform(args.source.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output_text, encoding="utf-8")
    os.chmod(args.output, 0o644)

    manifest = {
        "schema_version": 1,
        "source": str(args.source),
        "source_sha256": source_hash,
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        "behavior": (
            "skip Fluxon L2/IO observability deltas when the selected SGLang "
            "StorageMetrics type lacks the extension methods"
        ),
        "kv_data_path_changed": False,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
