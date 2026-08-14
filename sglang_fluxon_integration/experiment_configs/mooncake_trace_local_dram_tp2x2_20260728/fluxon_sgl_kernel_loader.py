#!/usr/bin/env python3
"""Load the run-scoped CUDA-13 Fluxon operators without touching a GPU."""

from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import threading
from types import ModuleType


EXPECTED_LIBRARY_SHA256 = (
    "c51270e0209cef87c0399d55459b7a30e93ce2f7cc769cdb11085134d83602fc"
)
EXPECTED_TORCH_VERSION = "2.11.0+cu130"
EXPECTED_TORCH_CUDA = "13.0"
CUDA_OPS = (
    "write_mha_pages_to_fluxon_values",
    "restore_mha_pages_from_fluxon_values",
    "write_mla_pages_to_fluxon_values",
    "restore_mla_pages_from_fluxon_values",
    "write_mamba_state_to_fluxon_values",
    "restore_mamba_state_from_fluxon_values",
)
LIBRARY_ENV = "FLUXON_SGL_KERNEL_OPS_LIBRARY"

_LOCK = threading.Lock()
_LOADED_PATH: Path | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_library_path() -> Path:
    return Path(__file__).resolve().with_name("fluxon_sgl_kernel_ops_cuda13.so")


def _load(candidate: Path, torch: ModuleType) -> Path:
    actual_hash = sha256(candidate)
    if actual_hash != EXPECTED_LIBRARY_SHA256:
        raise RuntimeError(
            "Fluxon SGL kernel library identity mismatch: "
            f"got={actual_hash} expected={EXPECTED_LIBRARY_SHA256} path={candidate}"
        )
    if torch.__version__ != EXPECTED_TORCH_VERSION:
        raise RuntimeError(
            "Fluxon SGL kernel requires Torch "
            f"{EXPECTED_TORCH_VERSION}, got {torch.__version__!r}"
        )
    if torch.version.cuda != EXPECTED_TORCH_CUDA:
        raise RuntimeError(
            "Fluxon SGL kernel requires Torch CUDA "
            f"{EXPECTED_TORCH_CUDA}, got {torch.version.cuda!r}"
        )

    torch.ops.load_library(str(candidate))
    missing = [
        name
        for name in CUDA_OPS
        if not torch._C._dispatch_has_kernel_for_dispatch_key(
            f"sgl_kernel::{name}", "CUDA"
        )
    ]
    if missing:
        raise RuntimeError(f"Fluxon SGL kernel CUDA registrations missing: {missing}")
    return candidate


def load_fluxon_sgl_kernel_ops(path: str | os.PathLike[str] | None = None) -> Path:
    """Load and validate the focused library exactly once in this process."""
    global _LOADED_PATH

    selected = path or os.environ.get(LIBRARY_ENV)
    candidate = Path(selected).resolve(strict=True) if selected else default_library_path()
    with _LOCK:
        if _LOADED_PATH is not None:
            if candidate != _LOADED_PATH:
                raise RuntimeError(
                    "Fluxon SGL kernel was already loaded from a different path: "
                    f"loaded={_LOADED_PATH} requested={candidate}"
                )
            return _LOADED_PATH
        torch = importlib.import_module("torch")
        _LOADED_PATH = _load(candidate, torch)
        return _LOADED_PATH
