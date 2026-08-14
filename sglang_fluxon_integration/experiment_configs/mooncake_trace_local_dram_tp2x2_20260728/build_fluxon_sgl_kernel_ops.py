#!/usr/bin/env python3
"""Build the focused CUDA-13 Fluxon additions to ``torch.ops.sgl_kernel``."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


EXPECTED_TRANSFER_SHA256 = "e9d325f52b51404f10bddb0cd2c4fec72b8fccb36ec0cab3c89cd70d1e95bdb6"
CUDA_OPS = (
    "write_mha_pages_to_fluxon_values",
    "restore_mha_pages_from_fluxon_values",
    "write_mla_pages_to_fluxon_values",
    "restore_mla_pages_from_fluxon_values",
    "write_mamba_state_to_fluxon_values",
    "restore_mamba_state_from_fluxon_values",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_nvme(path: Path) -> dict[str, str]:
    path.mkdir(parents=True, exist_ok=False)
    completed = subprocess.run(
        ["findmnt", "-T", str(path), "-n", "-o", "SOURCE,FSTYPE,TARGET"],
        check=True,
        text=True,
        capture_output=True,
    )
    fields = completed.stdout.split()
    if len(fields) != 3 or not fields[0].startswith("/dev/nvme"):
        raise SystemExit(f"build directory is not on NVMe: {completed.stdout!r}")
    return {"source": fields[0], "fstype": fields[1], "target": fields[2]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transfer-source", type=Path, required=True)
    parser.add_argument("--registry-source", type=Path, required=True)
    parser.add_argument("--compat-header", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if sha256(args.transfer_source) != EXPECTED_TRANSFER_SHA256:
        raise SystemExit("pinned Fluxon transfer.cu identity mismatch")
    mount = require_nvme(args.build_dir)
    source_dir = args.build_dir / "src"
    source_dir.mkdir()
    transfer = source_dir / "transfer.cu"
    registry = source_dir / "fluxon_sgl_kernel_registry.cpp"
    header = source_dir / "pytorch_extension_utils.h"
    shutil.copy2(args.transfer_source, transfer)
    shutil.copy2(args.registry_source, registry)
    shutil.copy2(args.compat_header, header)

    os.environ["TORCH_EXTENSIONS_DIR"] = str(args.build_dir / "torch_extensions")
    os.environ["TORCH_CUDA_ARCH_LIST"] = "9.0a"
    extension_dir = args.build_dir / "extension"
    extension_dir.mkdir()
    from torch.utils.cpp_extension import load

    library = Path(
        load(
            name="fluxon_sgl_kernel_ops_cuda13",
            sources=[str(transfer), str(registry)],
            extra_include_paths=[str(source_dir)],
            extra_cflags=["-O3"],
            extra_cuda_cflags=["-O3", "--threads=4"],
            extra_ldflags=["-ldl"],
            build_directory=str(extension_dir),
            verbose=True,
            is_python_module=False,
        )
    )

    import torch

    for name in CUDA_OPS:
        qualified = f"sgl_kernel::{name}"
        if not torch._C._dispatch_has_kernel_for_dispatch_key(qualified, "CUDA"):
            raise SystemExit(f"missing CUDA dispatch registration: {qualified}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    shutil.copy2(library, temporary)
    os.chmod(temporary, 0o555)
    os.replace(temporary, args.output)
    ldd = subprocess.run(
        ["ldd", str(args.output)], check=True, text=True, capture_output=True
    ).stdout
    if "not found" in ldd:
        raise SystemExit(f"focused extension has unresolved dependencies:\n{ldd}")

    value = {
        "schema_version": 1,
        "python": sys.version,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_arch_list": os.environ["TORCH_CUDA_ARCH_LIST"],
        "mount": mount,
        "transfer_source": str(args.transfer_source),
        "transfer_sha256": sha256(args.transfer_source),
        "registry_sha256": sha256(args.registry_source),
        "compat_header_sha256": sha256(args.compat_header),
        "library": str(args.output),
        "library_sha256": sha256(args.output),
        "library_bytes": args.output.stat().st_size,
        "cuda_ops": list(CUDA_OPS),
        "cpu_ops": [],
        "ldd": ldd.splitlines(),
    }
    args.manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
