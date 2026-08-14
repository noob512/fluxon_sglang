#!/usr/bin/env python3
"""Benchmark grouping adjacent Fluxon H2D layers into one CUDA batch call."""

import argparse
import statistics
import time

import torch
from sgl_kernel.kvcacheio import transfer_raw_h2d_batch


def measure(name, submit, repeats):
    stream = torch.cuda.Stream()
    submit_ms = []
    total_ms = []
    for repeat in range(repeats + 1):
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.cuda.stream(stream):
            submit()
        queued = time.perf_counter()
        stream.synchronize()
        done = time.perf_counter()
        if repeat:
            submit_ms.append((queued - start) * 1000.0)
            total_ms.append((done - start) * 1000.0)
    print(
        f"mode={name} submit_p50_ms={statistics.median(submit_ms):.3f} "
        f"total_p50_ms={statistics.median(total_ms):.3f} "
        f"total_min_ms={min(total_ms):.3f}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--layers", type=int, default=36)
    parser.add_argument("--pages", type=int, default=864)
    parser.add_argument("--page-bytes", type=int, default=65536)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--groups", type=int, nargs="+", default=(1, 2, 3, 4, 6, 9, 12)
    )
    args = parser.parse_args()
    torch.cuda.set_device(args.device)

    value_bytes = args.layers * 2 * args.page_bytes
    host = torch.empty(
        args.pages * value_bytes,
        dtype=torch.uint8,
        pin_memory=True,
    )
    host.fill_(73)
    value_ptrs = (
        torch.randperm(
            args.pages,
            generator=torch.Generator().manual_seed(20260721),
            dtype=torch.int64,
        )
        * value_bytes
        + host.data_ptr()
    )
    k_cache = torch.empty(
        (args.layers, args.pages, args.page_bytes),
        dtype=torch.uint8,
        device=f"cuda:{args.device}",
    )
    v_cache = torch.empty_like(k_cache)
    layer_offsets = torch.arange(args.layers, dtype=torch.int64).reshape(-1, 1)
    values = value_ptrs.reshape(1, -1)
    srcs = torch.cat(
        (
            values + layer_offsets * args.page_bytes,
            values
            + args.layers * args.page_bytes
            + layer_offsets * args.page_bytes,
        ),
        dim=1,
    ).contiguous()
    page_offsets = torch.arange(args.pages, dtype=torch.int64) * args.page_bytes
    k_bases = torch.tensor(
        [k_cache[layer].data_ptr() for layer in range(args.layers)],
        dtype=torch.int64,
    ).reshape(-1, 1)
    v_bases = torch.tensor(
        [v_cache[layer].data_ptr() for layer in range(args.layers)],
        dtype=torch.int64,
    ).reshape(-1, 1)
    dsts = torch.cat(
        (k_bases + page_offsets, v_bases + page_offsets), dim=1
    ).contiguous()
    sizes = torch.full_like(srcs, args.page_bytes)

    def grouped_submit(group_layers):
        for begin in range(0, args.layers, group_layers):
            end = min(begin + group_layers, args.layers)
            transfer_raw_h2d_batch(
                dsts[begin:end].reshape(-1),
                srcs[begin:end].reshape(-1),
                sizes[begin:end].reshape(-1),
                args.device,
            )

    print(
        f"layers={args.layers} pages={args.pages} "
        f"copy_gib={args.pages * value_bytes / 2**30:.3f}"
    )
    for group_layers in args.groups:
        if group_layers <= 0 or args.layers % group_layers:
            raise ValueError(
                f"group width must divide {args.layers}: {group_layers}"
            )
        measure(
            f"group_layers_{group_layers}",
            lambda group_layers=group_layers: grouped_submit(group_layers),
            args.repeats,
        )

    sample_step = max(1, k_cache.numel() // 4096)
    if not torch.all(k_cache.flatten()[::sample_step][:4096] == 73):
        raise RuntimeError("K validation failed")
    if not torch.all(v_cache.flatten()[::sample_step][:4096] == 73):
        raise RuntimeError("V validation failed")


if __name__ == "__main__":
    main()
