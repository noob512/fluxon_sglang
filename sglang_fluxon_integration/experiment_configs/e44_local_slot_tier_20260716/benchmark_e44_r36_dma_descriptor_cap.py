#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
from queue import Queue
from typing import Any

import torch
from sgl_kernel.kvcacheio import transfer_raw_h2d_batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--pages", default="288,576,864")
    parser.add_argument("--layers", type=int, default=36)
    parser.add_argument("--page-bytes", type=int, default=65536)
    parser.add_argument("--cap", type=int, default=1152)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    page_counts = [int(value) for value in args.pages.split(",")]
    if not page_counts or min(page_counts) <= 0:
        raise ValueError("--pages must contain positive integers")
    if args.cap <= 0:
        raise ValueError("--cap must be positive")

    torch.cuda.set_device(args.device)
    max_pages = max(page_counts)
    value_bytes = args.layers * 2 * args.page_bytes
    host = torch.empty(
        max_pages * value_bytes,
        dtype=torch.uint8,
        pin_memory=True,
    )
    host.fill_(73)
    value_ptrs = (
        torch.arange(max_pages, dtype=torch.int64) * value_bytes + host.data_ptr()
    )
    k_cache = torch.empty(
        (args.layers, max_pages, args.page_bytes),
        dtype=torch.uint8,
        device=f"cuda:{args.device}",
    )
    v_cache = torch.empty_like(k_cache)
    layer_offsets = torch.arange(args.layers, dtype=torch.int64).reshape(-1, 1)
    page_offsets = torch.arange(max_pages, dtype=torch.int64) * args.page_bytes
    srcs = torch.cat(
        (
            value_ptrs.reshape(1, -1) + layer_offsets * args.page_bytes,
            value_ptrs.reshape(1, -1)
            + args.layers * args.page_bytes
            + layer_offsets * args.page_bytes,
        ),
        dim=1,
    ).contiguous()
    dsts = torch.cat(
        (
            torch.tensor(
                [k_cache[layer].data_ptr() for layer in range(args.layers)],
                dtype=torch.int64,
            ).reshape(-1, 1)
            + page_offsets,
            torch.tensor(
                [v_cache[layer].data_ptr() for layer in range(args.layers)],
                dtype=torch.int64,
            ).reshape(-1, 1)
            + page_offsets,
        ),
        dim=1,
    ).contiguous()
    sizes = torch.full_like(srcs, args.page_bytes)

    result_queue: Queue[tuple[BaseException | None, Any]] = Queue()

    def worker() -> None:
        try:
            torch.cuda.set_device(args.device)
            stream = torch.cuda.Stream(device=args.device)
            results: list[dict[str, Any]] = []
            for pages in page_counts:
                descriptor_count = pages * 2
                for mode, cap in (("uncapped", 0), ("cap", args.cap)):
                    slices = (
                        ((0, descriptor_count),)
                        if cap <= 0 or descriptor_count <= cap
                        else tuple(
                            (start, min(start + cap, descriptor_count))
                            for start in range(0, descriptor_count, cap)
                        )
                    )
                    submit_ms: list[float] = []
                    total_ms: list[float] = []
                    for repeat in range(args.repeats + 1):
                        torch.cuda.synchronize(args.device)
                        start = time.perf_counter()
                        with torch.cuda.device(args.device), torch.cuda.stream(stream):
                            for layer in range(args.layers):
                                for begin, end in slices:
                                    transfer_raw_h2d_batch(
                                        dsts[layer, begin:end],
                                        srcs[layer, begin:end],
                                        sizes[layer, begin:end],
                                        args.device,
                                    )
                        submitted = time.perf_counter()
                        stream.synchronize()
                        completed = time.perf_counter()
                        if repeat > 0:
                            submit_ms.append((submitted - start) * 1000.0)
                            total_ms.append((completed - start) * 1000.0)
                    results.append(
                        {
                            "mode": mode,
                            "pages": pages,
                            "descriptors_per_layer": descriptor_count,
                            "calls_per_layer": len(slices),
                            "copy_gib": pages * value_bytes / 2**30,
                            "submit_mean_ms": statistics.mean(submit_ms),
                            "submit_p50_ms": statistics.median(submit_ms),
                            "submit_max_ms": max(submit_ms),
                            "total_mean_ms": statistics.mean(total_ms),
                            "total_p50_ms": statistics.median(total_ms),
                            "total_max_ms": max(total_ms),
                        }
                    )
            result_queue.put((None, results))
        except BaseException as exc:
            result_queue.put((exc, None))

    thread = threading.Thread(target=worker, name="e44-r36-dma-cap")
    thread.start()
    thread.join(timeout=180)
    if thread.is_alive():
        raise RuntimeError("r36 DMA cap benchmark timed out")
    error, results = result_queue.get_nowait()
    if error is not None:
        raise RuntimeError("r36 DMA cap benchmark worker failed") from error

    sample_stride = max(1, k_cache.numel() // 4096)
    if not torch.all(k_cache.flatten()[::sample_stride][:4096] == 73):
        raise RuntimeError("K validation failed")
    if not torch.all(v_cache.flatten()[::sample_stride][:4096] == 73):
        raise RuntimeError("V validation failed")
    for result in results:
        expected_calls = (
            1
            if result["mode"] == "uncapped"
            else math.ceil(result["descriptors_per_layer"] / args.cap)
        )
        if result["calls_per_layer"] != expected_calls:
            raise RuntimeError(f"unexpected call count: {result}")

    print(
        json.dumps(
            {
                "schema": "e44_r36_dma_descriptor_cap_benchmark_v1",
                "device": args.device,
                "layers": args.layers,
                "page_bytes": args.page_bytes,
                "cap": args.cap,
                "repeats": args.repeats,
                "results": results,
                "data_validation": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
