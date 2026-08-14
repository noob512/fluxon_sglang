#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


METHODS = {
    "_fluxon_hostless_dma_descriptor_slices",
    "_enqueue_fluxon_hostless_layer_batch_dma",
    "_submit_fluxon_hostless_layer_batch_dma_background",
}
MARKERS = (
    "SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL",
    "descriptors_per_layer=%d dma_calls=%d",
    "max_descriptors_per_call=%d",
)


class NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False


class FakeCuda:
    def __init__(self) -> None:
        self.devices: list[int] = []

    def set_device(self, device: int) -> None:
        self.devices.append(device)

    def device(self, device: int) -> NullContext:
        return NullContext()

    def stream(self, stream: Any) -> NullContext:
        return NullContext()


class FakeVector:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def tolist(self) -> list[int]:
        return list(self.values)


class FakeTensor:
    def __init__(self, rows: list[list[int]]) -> None:
        self.rows = rows
        self.shape = (len(rows), len(rows[0]) if rows else 0)

    def __getitem__(self, key: tuple[int, slice]) -> FakeVector:
        row, column_slice = key
        return FakeVector(self.rows[row][column_slice])


class Producer:
    def __init__(self) -> None:
        self.completed: list[int] = []
        self.start_event = SimpleNamespace(wait=lambda stream: None)

    def complete(self, layer: int) -> None:
        self.completed.append(layer)


class Guard:
    def __init__(self) -> None:
        self.submitted: list[int] = []
        self.failures: list[BaseException] = []
        self.uninstalled = False

    def mark_submitted(self, layer: int) -> None:
        self.submitted.append(layer)

    def fail(self, error: BaseException) -> None:
        self.failures.append(error)

    def uninstall(self) -> None:
        self.uninstalled = True


def extract_harness(source_path: Path) -> tuple[type, dict[str, Any]]:
    source_text = source_path.read_text(encoding="utf-8")
    for marker in MARKERS:
        if marker not in source_text:
            raise AssertionError(f"missing r36 marker: {marker}")
    tree = ast.parse(source_text, filename=str(source_path))
    source_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UnifiedRadixCache"
    )
    methods = [
        node
        for node in source_class.body
        if isinstance(node, ast.FunctionDef) and node.name in METHODS
    ]
    found = {method.name for method in methods}
    if found != METHODS:
        raise AssertionError(f"missing methods: {sorted(METHODS - found)}")
    harness = ast.ClassDef(
        name="ChunkHarness",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[]))
    fake_torch = SimpleNamespace(cuda=FakeCuda())
    namespace: dict[str, Any] = {
        "Any": Any,
        "_FluxonHostlessLayerwiseLoad": Any,
        "logger": logging.getLogger("e44_r36_dma_chunk_validator"),
        "time": time,
        "torch": fake_torch,
        "transfer_raw_h2d_batch": None,
    }
    exec(compile(module, "<r36-dma-chunk-harness>", "exec"), namespace)
    return namespace["ChunkHarness"], namespace


def assert_layer_descriptors(calls: list[tuple[list[int], list[int], list[int], int]]) -> None:
    if len(calls) != 6:
        raise AssertionError(f"expected 6 chunk calls, got {len(calls)}")
    for layer in range(2):
        layer_calls = calls[layer * 3 : (layer + 1) * 3]
        expected_base = layer * 10
        expected_src = list(range(expected_base, expected_base + 10))
        expected_dst = list(range(100 + expected_base, 110 + expected_base))
        expected_size = list(range(200 + expected_base, 210 + expected_base))
        if [value for call in layer_calls for value in call[1]] != expected_src:
            raise AssertionError(f"layer {layer} source descriptors changed")
        if [value for call in layer_calls for value in call[0]] != expected_dst:
            raise AssertionError(f"layer {layer} destination descriptors changed")
        if [value for call in layer_calls for value in call[2]] != expected_size:
            raise AssertionError(f"layer {layer} size descriptors changed")
        if [len(call[0]) for call in layer_calls] != [4, 4, 2]:
            raise AssertionError(f"layer {layer} chunk sizes are not 4/4/2")
        if any(call[3] != 3 for call in layer_calls):
            raise AssertionError(f"layer {layer} used the wrong CUDA device")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()

    harness_type, namespace = extract_harness(args.source)
    cache = harness_type()
    cache.cache_controller = SimpleNamespace()
    cache._fluxon_hostless_dma_max_descriptors_per_call = 4
    cache._cuda_device_index = lambda: 3
    cache._fluxon_hostless_background_dma_stream = lambda: object()

    if cache._fluxon_hostless_dma_descriptor_slices(10) != ((0, 4), (4, 8), (8, 10)):
        raise AssertionError("descriptor cap did not produce 4/4/2 chunks")
    cache._fluxon_hostless_dma_max_descriptors_per_call = 0
    if cache._fluxon_hostless_dma_descriptor_slices(10) != ((0, 10),):
        raise AssertionError("zero descriptor cap did not preserve one call")
    cache._fluxon_hostless_dma_max_descriptors_per_call = 4

    dma_plan = {
        "plan": {"layer_num": 2},
        "src_ptrs": FakeTensor([list(range(10)), list(range(10, 20))]),
        "dst_ptrs": FakeTensor([list(range(100, 110)), list(range(110, 120))]),
        "size_bytes": FakeTensor([list(range(200, 210)), list(range(210, 220))]),
        "page_count": 10,
    }
    calls: list[tuple[list[int], list[int], list[int], int]] = []
    namespace["transfer_raw_h2d_batch"] = (
        lambda dst, src, size, device: calls.append(
            (dst.tolist(), src.tolist(), size.tolist(), device)
        )
    )

    producer = Producer()
    cache._enqueue_fluxon_hostless_layer_batch_dma(dma_plan, producer)
    assert_layer_descriptors(calls)
    if producer.completed != [0, 1]:
        raise AssertionError("synchronous path did not publish one event per layer")

    calls.clear()
    producer = Producer()
    guard = Guard()
    operation = SimpleNamespace(token_count=64, background_submit_cpu_ms=None)
    cache._submit_fluxon_hostless_layer_batch_dma_background(
        dma_plan,
        producer,
        guard,
        [operation],
    )
    assert_layer_descriptors(calls)
    if producer.completed != [0, 1] or guard.submitted != [0, 1]:
        raise AssertionError("background path published a partial layer chunk")
    if guard.failures or not guard.uninstalled:
        raise AssertionError("background success did not close its guard cleanly")
    if operation.background_submit_cpu_ms is None:
        raise AssertionError("background submit duration was not published")

    print("e44 r36 DMA descriptor chunk validation: passed")


if __name__ == "__main__":
    main()
