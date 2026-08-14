#!/usr/bin/env python3
"""Derive a common-two-rail launcher overlay from the sealed p8 launchers.

The p8 GPU launcher configures four PPLX domains while the remote CPU owner
configures two.  PPLX requires every peer memory descriptor to contain exactly
one address/rkey pair per local domain, so that asymmetric configuration makes
Single and Paged submissions fail.  This overlay changes only the GPU owner and
external clients to ``mlx5_0,mlx5_1``; the remote CPU launcher is already on
that pair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


EXPECTED_INNER_SHA256 = (
    "314518a086b1d18aa7ee40340ed95a662a644f8d6fcf58923d57089c725e02cd"
)
EXPECTED_WRAPPER_SHA256 = (
    "6324195bd76dfd24b3feaa096e075a2d6923e6943fd6393d789467cce9ad14b9"
)
EXPECTED_BASE_REPLAYER_SHA256 = (
    "98a797ad20f1b5b6cb078e87cf7e1e9a24773963b9d3ba3a8b67594d96d6153b"
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


def derive_inner(text: str) -> str:
    text = replace_exact(
        text,
        "# Derived for Mooncake Conversation F: one 256-GiB owner, two TP2 "
        "external clients, four HCAs.\n",
        "# Derived for Mooncake Conversation F p9: one 256-GiB owner, two TP2 "
        "external clients, common two-rail PPLX.\n",
    )
    text = replace_exact(
        text,
        'RDMA_DEVICE_2="${FLUXON_EXTERNAL_RDMA_DEVICE_2:?missing '
        'FLUXON_EXTERNAL_RDMA_DEVICE_2}"\n'
        'RDMA_DEVICE_3="${FLUXON_EXTERNAL_RDMA_DEVICE_3:?missing '
        'FLUXON_EXTERNAL_RDMA_DEVICE_3}"\n',
        "",
    )
    text = replace_exact(
        text,
        '  - "${RDMA_DEVICE_2}"\n  - "${RDMA_DEVICE_3}"\n',
        "",
        expected_count=2,
    )
    return text


def derive_wrapper(text: str) -> str:
    text = replace_exact(
        text,
        "  for hca in mlx5_0 mlx5_1 mlx5_2 mlx5_3; do",
        "  for hca in mlx5_0 mlx5_1; do",
    )
    text = replace_exact(
        text,
        "  FLUXON_EXTERNAL_RDMA_DEVICE_2=mlx5_2\n"
        "  FLUXON_EXTERNAL_RDMA_DEVICE_3=mlx5_3\n",
        "",
    )
    text = replace_exact(
        text,
        '  echo "h2d_mode layer_batch_dma=$layer_batch_dma '
        'background_dma_submit=$background_dma_submit"\n',
        '  echo "h2d_mode layer_batch_dma=$layer_batch_dma '
        'background_dma_submit=$background_dma_submit"\n'
        '  echo "pplx_rails local=2 remote=2 devices=mlx5_0,mlx5_1"\n',
    )
    return text


def derive_base_replayer(text: str) -> str:
    text = replace_exact(
        text,
        "LOCAL_TOTAL_BYTES = 274_877_906_944\nTCP_CONNECTOR_CONFIG = {",
        "LOCAL_TOTAL_BYTES = 274_877_906_944\n"
        'FLUXON_F_FOUR_RAIL_HCAS = ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"]\n'
        'FLUXON_F_COMMON_TWO_RAIL_HCAS = ["mlx5_0", "mlx5_1"]\n'
        "TCP_CONNECTOR_CONFIG = {",
    )
    text = replace_exact(
        text,
        '        if local.get("rdma_hcas") != '
        '["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"]:\n'
        '            raise ValidationError("group F local HCA list mismatch")',
        '        rdma_profile = value.get("rdma_profile", "legacy_four_rail")\n'
        '        if rdma_profile == "legacy_four_rail":\n'
        "            expected_local_hcas = FLUXON_F_FOUR_RAIL_HCAS\n"
        '        elif rdma_profile == "pplx_common_two_rail":\n'
        "            expected_local_hcas = FLUXON_F_COMMON_TWO_RAIL_HCAS\n"
        "        else:\n"
        '            raise ValidationError("group F RDMA profile is unsupported")\n'
        '        if local.get("rdma_hcas") != expected_local_hcas:\n'
        '            raise ValidationError("group F local HCA list/profile mismatch")',
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
    parser.add_argument("--inner-source", type=Path, required=True)
    parser.add_argument("--wrapper-source", type=Path, required=True)
    parser.add_argument("--base-replayer-source", type=Path, required=True)
    parser.add_argument("--inner-output", type=Path, required=True)
    parser.add_argument("--wrapper-output", type=Path, required=True)
    parser.add_argument("--base-replayer-output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    identities = {
        "inner": sha256(args.inner_source),
        "wrapper": sha256(args.wrapper_source),
        "base_replayer": sha256(args.base_replayer_source),
    }
    expected = {
        "inner": EXPECTED_INNER_SHA256,
        "wrapper": EXPECTED_WRAPPER_SHA256,
        "base_replayer": EXPECTED_BASE_REPLAYER_SHA256,
    }
    if identities != expected:
        raise SystemExit(
            "p8 launcher identity mismatch: "
            f"actual={identities!r} expected={expected!r}"
        )

    try:
        inner = derive_inner(args.inner_source.read_text(encoding="utf-8"))
        wrapper = derive_wrapper(args.wrapper_source.read_text(encoding="utf-8"))
        base_replayer = derive_base_replayer(
            args.base_replayer_source.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise SystemExit(f"refusing two-rail derivation: {exc}") from exc

    write_new(args.inner_output, inner, 0o555)
    write_new(args.wrapper_output, wrapper, 0o555)
    write_new(args.base_replayer_output, base_replayer, 0o444)
    manifest = {
        "schema": "fluxon_f_p9_common_two_rail_overlay_v1",
        "source_sha256": identities,
        "output_sha256": {
            "inner": sha256(args.inner_output),
            "wrapper": sha256(args.wrapper_output),
            "base_replayer": sha256(args.base_replayer_output),
        },
        "pplx_domains": {
            "gpu_local_owner": ["mlx5_0", "mlx5_1"],
            "external_clients": ["mlx5_0", "mlx5_1"],
            "remote_cpu_owner": ["mlx5_0", "mlx5_1"],
        },
        "unchanged": [
            "p7 radix runtime",
            "p8 layer-batch background H2D",
            "local and remote DRAM capacity",
            "GDR disabled",
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
