#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

import torch
from sgl_kernel.kvcacheio import restore_mla_pages_from_fluxon_values


PLAN_BLOB_MAGIC = 0x4658504C414E5631


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--layers", type=int, default=3)
    parser.add_argument("--page-bytes", type=int, default=65536)
    args = parser.parse_args()

    if args.pages <= 0 or args.layers <= 0 or args.page_bytes <= 0:
        raise ValueError("pages, layers, and page-bytes must be positive")

    torch.cuda.set_device(args.device)
    device = torch.device("cuda", args.device)
    total_page_bytes = args.layers * args.page_bytes
    source = torch.arange(
        args.pages * total_page_bytes,
        dtype=torch.int64,
        device=device,
    ).remainder_(251).to(torch.uint8)
    source = source.reshape(args.pages, total_page_bytes).contiguous()

    destination_page_count = args.pages * 2 + 1
    destination = torch.full(
        (args.layers, destination_page_count, args.page_bytes),
        255,
        dtype=torch.uint8,
        device=device,
    )
    destination_indices = torch.arange(
        1,
        1 + args.pages * 2,
        2,
        dtype=torch.int64,
        device=device,
    )
    destination_layer_ptrs = torch.tensor(
        [destination[layer].data_ptr() for layer in range(args.layers)],
        dtype=torch.int64,
        device=device,
    )

    value_ptrs = [
        source.data_ptr() + page * total_page_bytes
        for page in range(args.pages)
    ]
    plan_blob = torch.empty(
        args.pages + 2,
        dtype=torch.int64,
        pin_memory=True,
    )
    plan_blob[0] = PLAN_BLOB_MAGIC
    plan_blob[1] = args.pages
    plan_blob[2:] = torch.tensor(value_ptrs, dtype=torch.int64)

    torch.cuda.synchronize(device)
    started_at = time.perf_counter()
    restore_mla_pages_from_fluxon_values(
        plan_blob.data_ptr(),
        destination_indices,
        destination_layer_ptrs,
        args.page_bytes,
        args.device,
    )
    torch.cuda.synchronize(device)
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    for layer in range(args.layers):
        expected = source[
            :,
            layer * args.page_bytes : (layer + 1) * args.page_bytes,
        ]
        actual = destination[layer].index_select(0, destination_indices)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)

    untouched_mask = torch.ones(destination_page_count, dtype=torch.bool, device=device)
    untouched_mask[destination_indices] = False
    untouched = destination[:, untouched_mask]
    if not bool(torch.all(untouched == 255).item()):
        raise AssertionError("D2D scatter modified an unselected destination page")

    layerwise_destination = torch.full_like(destination, 255)
    layerwise_plan_blobs = torch.empty(
        (args.layers, args.pages + 2),
        dtype=torch.int64,
        pin_memory=True,
    )
    layerwise_plan_blobs[:, 0] = PLAN_BLOB_MAGIC
    layerwise_plan_blobs[:, 1] = args.pages
    base_ptrs = torch.tensor(value_ptrs, dtype=torch.int64).reshape(1, -1)
    layer_offsets = (
        torch.arange(args.layers, dtype=torch.int64).reshape(-1, 1)
        * args.page_bytes
    )
    layerwise_plan_blobs[:, 2:] = base_ptrs + layer_offsets
    layerwise_destination_ptrs = torch.tensor(
        [
            layerwise_destination[layer].data_ptr()
            for layer in range(args.layers)
        ],
        dtype=torch.int64,
        device=device,
    )

    torch.cuda.synchronize(device)
    layerwise_started_at = time.perf_counter()
    for layer in range(args.layers):
        restore_mla_pages_from_fluxon_values(
            layerwise_plan_blobs[layer].data_ptr(),
            destination_indices,
            layerwise_destination_ptrs[layer : layer + 1],
            args.page_bytes,
            args.device,
        )
    torch.cuda.synchronize(device)
    layerwise_elapsed_ms = (time.perf_counter() - layerwise_started_at) * 1000.0

    for layer in range(args.layers):
        expected = source[
            :,
            layer * args.page_bytes : (layer + 1) * args.page_bytes,
        ]
        actual = layerwise_destination[layer].index_select(
            0, destination_indices
        )
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    layerwise_untouched = layerwise_destination[:, untouched_mask]
    if not bool(torch.all(layerwise_untouched == 255).item()):
        raise AssertionError(
            "layerwise D2D scatter modified an unselected destination page"
        )

    print(
        json.dumps(
            {
                "status": "passed",
                "device": args.device,
                "pages": args.pages,
                "layers": args.layers,
                "page_bytes": args.page_bytes,
                "bytes": args.pages * total_page_bytes,
                "elapsed_ms": elapsed_ms,
                "layerwise_elapsed_ms": layerwise_elapsed_ms,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
