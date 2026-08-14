#!/usr/bin/env python3
"""Materialize the exact CPython-3.10 group-E wheelhouse from a pip report."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from packaging.utils import canonicalize_name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_identity(path: Path) -> tuple[str, str, tuple[str, ...]]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA") and name.count("/") == 1
        ]
        wheel_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/WHEEL") and name.count("/") == 1
        ]
        if len(metadata_names) != 1 or len(wheel_names) != 1:
            raise SystemExit(f"invalid wheel metadata layout: {path}")
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_names[0]))
        wheel_text = archive.read(wheel_names[0]).decode()
    tags = tuple(
        line.split(":", 1)[1].strip()
        for line in wheel_text.splitlines()
        if line.startswith("Tag:")
    )
    return canonicalize_name(metadata["Name"]), metadata["Version"], tags


def cp310_compatible(tags: tuple[str, ...]) -> bool:
    for tag in tags:
        interpreter, abi, platform = tag.split("-", 2)
        if platform != "any" and not (
            platform == "linux_x86_64" or "x86_64" in platform
        ):
            continue
        if interpreter in {"py2.py3", "py3", "cp310"}:
            return True
        match = re.fullmatch(r"cp(3[6-9])", interpreter)
        if match and abi == "abi3":
            return True
    return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    report = json.loads(args.report.read_text())
    requirements: dict[str, str] = {}
    for item in report.get("install", []):
        metadata = item.get("metadata", {})
        name = canonicalize_name(metadata.get("name", ""))
        version = metadata.get("version")
        if not name or not version or name in requirements:
            raise SystemExit(f"invalid or duplicate report distribution: {metadata}")
        requirements[name] = version
    if len(requirements) != 101:
        raise SystemExit(f"expected 101 report distributions, found {len(requirements)}")

    candidates: dict[tuple[str, str], list[tuple[Path, tuple[str, ...]]]] = {}
    for wheel in sorted(args.source.glob("*.whl")):
        name, version, tags = wheel_identity(wheel)
        if cp310_compatible(tags):
            candidates.setdefault((name, version), []).append((wheel, tags))

    selected: list[Path] = []
    identities = []
    for name, version in sorted(requirements.items()):
        matches = candidates.get((name, version), [])
        if len(matches) != 1:
            raise SystemExit(
                f"expected one CPython-3.10 wheel for {name}=={version}, found "
                f"{[(item[0].name, item[1]) for item in matches]}"
            )
        wheel, tags = matches[0]
        selected.append(wheel)
        identities.append(
            {
                "name": name,
                "version": version,
                "filename": wheel.name,
                "tags": list(tags),
                "bytes": wheel.stat().st_size,
                "sha256": sha256_file(wheel),
            }
        )

    args.output.mkdir(parents=True, mode=0o755)
    for wheel in selected:
        os.link(wheel, args.output / wheel.name)
    manifest_lines = [
        f"{item['sha256']}  {item['filename']}" for item in sorted(identities, key=lambda x: x["filename"])
    ]
    manifest_bytes = ("\n".join(manifest_lines) + "\n").encode()
    manifest_path = args.output / "WHEELS.sha256"
    with manifest_path.open("xb") as handle:
        handle.write(manifest_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    resolution = {
        "schema": "vllm_lmcache_wheelhouse_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "python_target": "cp310",
        "platform_target": "x86_64 Linux",
        "pip_report": {
            "path": str(args.report.resolve()),
            "sha256": sha256_file(args.report),
        },
        "wheel_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "wheel_count": len(identities),
        "wheel_bytes": sum(item["bytes"] for item in identities),
        "wheels": identities,
        "generator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    encoded = (
        json.dumps(resolution, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    with (args.output / "RESOLUTION.json").open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(resolution, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
