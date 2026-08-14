#!/usr/bin/env python3
"""Disable Fluxon GPU-direct staging in the isolated F SGLang runtime.

The Fluxon wheel and host-RDMA transport remain unchanged.  This transform
only prevents SGLang from configuring or admitting registered GPU staging, so
remote Get uses the existing planned CPU fallback followed by local H2D.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path


EXPECTED_SOURCE_SHA256 = (
    "e70a740e5cbd4f3c8815953103157db1c2ff602c2868d443638dcb6a22892f68"
)

TRANSFORMS = (
    (
        "_FLUXON_GPU_DIRECT_STAGING_SLOT_COUNT = 288\n"
        "if _is_cuda or _is_hip:\n",
        "_FLUXON_GPU_DIRECT_STAGING_SLOT_COUNT = 288\n"
        "_FLUXON_GPU_DIRECT_STAGING_ENABLED = False\n"
        "if _is_cuda or _is_hip:\n",
    ),
    (
        "            if str(storage_backend).lower() == \"fluxon\":\n"
        "                self._configure_fluxon_gpu_direct_staging()\n",
        "            if str(storage_backend).lower() == \"fluxon\":\n"
        "                if _FLUXON_GPU_DIRECT_STAGING_ENABLED:\n"
        "                    self._configure_fluxon_gpu_direct_staging()\n"
        "                else:\n"
        "                    logger.warning(\n"
        "                        \"Fluxon GPU-direct staging disabled: mode=cpu_h2d_only\"\n"
        "                    )\n",
    ),
    (
        "            gpu_admission_block_reason = None\n"
        "            if not kv_prefetch_enabled:\n",
        "            gpu_admission_block_reason = None\n"
        "            if not _FLUXON_GPU_DIRECT_STAGING_ENABLED:\n"
        "                gpu_admission_block_reason = \"disabled\"\n"
        "            elif not kv_prefetch_enabled:\n",
    ),
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_output(text: str) -> None:
    tree = ast.parse(text)
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_FLUXON_GPU_DIRECT_STAGING_ENABLED"
            for target in node.targets
        )
    ]
    if len(assignments) != 1:
        raise ValueError("GDR-off runtime must define one immutable staging gate")
    value = assignments[0].value
    if not isinstance(value, ast.Constant) or value.value is not False:
        raise ValueError("GDR-off runtime gate must be literal False")
    required = (
        "Fluxon GPU-direct staging disabled: mode=cpu_h2d_only",
        "gpu_admission_block_reason = \"disabled\"",
        "if _FLUXON_GPU_DIRECT_STAGING_ENABLED:",
        "if not _FLUXON_GPU_DIRECT_STAGING_ENABLED:",
    )
    for marker in required:
        if marker not in text:
            raise ValueError(f"GDR-off runtime marker missing: {marker}")


def transform(source: bytes) -> bytes:
    source_hash = sha256_bytes(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "kernel-loaded unified radix identity mismatch: "
            f"got={source_hash} expected={EXPECTED_SOURCE_SHA256}"
        )
    text = source.decode("utf-8")
    for old, new in TRANSFORMS:
        count = text.count(old)
        if count != 1:
            raise ValueError(
                "GDR-off transform anchor count mismatch: "
                f"count={count} anchor={old.splitlines()[0]!r}"
            )
        text = text.replace(old, new, 1)
    validate_output(text)
    return text.encode("utf-8")


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
    os.chmod(args.output, 0o644)
    manifest = {
        "schema_version": 1,
        "source": str(args.source),
        "source_sha256": sha256_bytes(source),
        "output": str(args.output),
        "output_sha256": sha256_bytes(output),
        "gpu_direct_staging": "disabled",
        "remote_get_path": "planned_cpu_fallback_then_local_h2d",
        "host_rdma": "unchanged",
        "fluxon_wheel_changed": False,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
