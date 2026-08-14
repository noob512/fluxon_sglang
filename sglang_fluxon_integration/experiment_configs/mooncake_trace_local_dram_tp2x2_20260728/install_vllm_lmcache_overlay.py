#!/usr/bin/env python3
"""Install and seal the group-E Python overlay from an audited wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--wheel-manifest-sha256", required=True)
    parser.add_argument("--target", type=Path, required=True)
    return parser.parse_args(argv)


def load_wheel_manifest(path: Path, expected_sha256: str) -> list[Path]:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise SystemExit("invalid expected wheel manifest SHA256")
    if sha256_file(path) != expected_sha256:
        raise SystemExit("wheel manifest SHA256 mismatch")
    wheels: list[Path] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        parts = line.split("  ", 1)
        if len(parts) != 2 or not SHA256_RE.fullmatch(parts[0]):
            raise SystemExit(f"invalid wheel manifest line {line_number}")
        name = parts[1]
        if name in seen or Path(name).name != name or not name.endswith(".whl"):
            raise SystemExit(f"unsafe or duplicate wheel name on line {line_number}")
        seen.add(name)
        wheel = path.parent / name
        if not wheel.is_file() or sha256_file(wheel) != parts[0]:
            raise SystemExit(f"wheel hash mismatch: {name}")
        wheels.append(wheel)
    if len(wheels) != 101:
        raise SystemExit(f"expected 101 resolved wheels, found {len(wheels)}")
    return wheels


def tree_digest(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = 0
    size = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "OVERLAY_MANIFEST.json" or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        file_size = path.stat().st_size
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(str(file_size).encode())
        digest.update(b"\0")
        digest.update(file_hash.encode())
        digest.update(b"\n")
        files += 1
        size += file_size
    return digest.hexdigest(), files, size


def run_import_smoke(target: Path) -> dict[str, Any]:
    code = r"""
import importlib.metadata
import json
import torch
import vllm
import vllm._C_stable_libtorch
import vllm._moe_C_stable_libtorch
import lmcache
from lmcache.integration.vllm.lmcache_connector_v1 import LMCacheConnectorV1Dynamic
from lmcache.v1.storage_backend.connector.mooncakestore_connector import MooncakestoreConnector
from mooncake.store import MooncakeDistributedStore

print(json.dumps({
    "vllm": importlib.metadata.version("vllm"),
    "lmcache": importlib.metadata.version("lmcache"),
    "mooncake": importlib.metadata.version("mooncake-transfer-engine"),
    "torch": torch.__version__,
    "torch_cuda": torch.version.cuda,
    "cuda_available": torch.cuda.is_available(),
    "gpu_count": torch.cuda.device_count(),
    "lmcache_connector": LMCacheConnectorV1Dynamic.__name__,
    "mooncake_connector": MooncakestoreConnector.__name__,
    "mooncake_store": MooncakeDistributedStore.__name__,
}, sort_keys=True))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "overlay import smoke failed: "
            f"rc={completed.returncode} stdout={completed.stdout!r} "
            f"stderr={completed.stderr!r}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if len(lines) != 1:
        raise SystemExit(f"unexpected import smoke output: {completed.stdout!r}")
    value = json.loads(lines[0])
    if value.get("vllm") != "0.24.0" or value.get("lmcache") != "0.5.2":
        raise SystemExit(f"installed version mismatch: {value}")
    if value.get("mooncake") != "0.3.11.post1":
        raise SystemExit(f"Mooncake base version mismatch: {value}")
    if value.get("torch") not in ("2.11.0", "2.11.0+cu130"):
        raise SystemExit(f"Torch base version mismatch: {value}")
    if value.get("gpu_count", 0) < 4 or not value.get("cuda_available"):
        raise SystemExit(f"GPU import smoke failed: {value}")
    value["stderr_tail"] = completed.stderr[-8192:]
    return value


def installed_distributions(target: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for distribution in importlib.metadata.distributions(path=[str(target)]):
        name = distribution.metadata.get("Name")
        if name:
            values[name] = distribution.version
    return dict(sorted(values.items(), key=lambda item: item[0].lower()))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    wheelhouse = args.wheelhouse.resolve()
    target = args.target
    if not str(target).startswith("/tmp/") or target.exists():
        raise SystemExit("target must be a new absolute path below /tmp")
    manifest_path = wheelhouse / "WHEELS.sha256"
    wheels = load_wheel_manifest(manifest_path, args.wheel_manifest_sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(mode=0o755)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--no-compile",
        "--target",
        str(target),
        *map(str, wheels),
    ]
    subprocess.run(command, check=True)
    smoke = run_import_smoke(target)
    distributions = installed_distributions(target)
    if len(distributions) != 101:
        raise SystemExit(
            f"expected 101 installed overlay distributions, found {len(distributions)}"
        )
    digest, files, size = tree_digest(target)
    value = {
        "schema": "vllm_lmcache_overlay_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "target": str(target.resolve()),
        "python": sys.version,
        "python_executable": sys.executable,
        "wheel_manifest_sha256": args.wheel_manifest_sha256,
        "wheel_count": len(wheels),
        "installed_distributions": distributions,
        "import_smoke": smoke,
        "tree_sha256": digest,
        "tree_files": files,
        "tree_bytes": size,
        "installer": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
            "pid": os.getpid(),
        },
    }
    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    output = target / "OVERLAY_MANIFEST.json"
    with output.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"manifest_sha256": hashlib.sha256(encoded).hexdigest(), **value}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
