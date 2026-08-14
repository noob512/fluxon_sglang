#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import io
import logging
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any


HELPER_METHODS = {
    "_fluxon_hostless_tp_rank",
    "_observe_fluxon_hostless_request",
    "_finish_fluxon_hostless_request_observation",
    "_log_fluxon_hostless_observation_snapshot",
    "_new_fluxon_hostless_eviction_observation",
    "_active_fluxon_hostless_eviction_observation",
}

REQUIRED_MARKERS = (
    "Fluxon hostless request lifecycle:",
    '"below_threshold"',
    '"rate_limited"',
    '"tp_no_common_prefix"',
    '"evict_already_backed_tokens"',
    '"evict_after_writeback_tokens"',
    '"evict_write_wait_ms"',
    'f"load_back_{last_recoverable_error_kind}"',
    '"load_back_consumed"',
)


def extract_helper_class(tree: ast.Module) -> tuple[type, io.StringIO]:
    source_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UnifiedRadixCache"
    )
    methods = [
        node
        for node in source_class.body
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_METHODS
    ]
    found = {node.name for node in methods}
    if found != HELPER_METHODS:
        raise AssertionError(
            f"observation helper mismatch: missing={sorted(HELPER_METHODS - found)}"
        )
    harness = ast.ClassDef(
        name="ObservationHarness",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[]))
    stream = io.StringIO()
    logger = logging.getLogger("e44_r35_observation_validator")
    logger.handlers[:] = [logging.StreamHandler(stream)]
    logger.setLevel(logging.INFO)
    namespace = {
        "Any": Any,
        "defaultdict": defaultdict,
        "logger": logger,
        "time": time,
    }
    exec(compile(module, "<r35-observation-helpers>", "exec"), namespace)
    return namespace["ObservationHarness"], stream


def validate_helpers(harness_type: type, stream: io.StringIO) -> None:
    cache = harness_type()
    cache.cache_controller = SimpleNamespace(tp_rank=1)
    cache._fluxon_hostless_request_observations = {}
    cache._fluxon_hostless_observation_counters = defaultdict(int)
    cache._fluxon_hostless_eviction_observation_stack = []

    observation = cache._observe_fluxon_hostless_request(
        "req-1",
        prefetch_decision="rate_limited",
        host_hit_tokens=128,
    )
    if observation["host_hit_tokens"] != 128:
        raise AssertionError("request observation did not retain host_hit_tokens")

    eviction = cache._new_fluxon_hostless_eviction_observation(64)
    eviction.update(
        evict_actual_tokens=64,
        evict_already_backed_tokens=64,
    )
    cache._fluxon_hostless_eviction_observation_stack.append(eviction)
    if cache._active_fluxon_hostless_eviction_observation() is not eviction:
        raise AssertionError("active eviction observation is not stack-scoped")
    cache._fluxon_hostless_eviction_observation_stack.pop()

    cache._finish_fluxon_hostless_request_observation(
        "req-1",
        "load_back_not_ready",
        **eviction,
    )
    if "req-1" in cache._fluxon_hostless_request_observations:
        raise AssertionError("terminal observation was not removed")
    counters = cache._fluxon_hostless_observation_counters
    if counters["terminal.load_back_not_ready"] != 1:
        raise AssertionError("terminal counter mismatch")
    if counters["decision.rate_limited"] != 1:
        raise AssertionError("decision counter mismatch")

    cache._log_fluxon_hostless_observation_snapshot("unit_test")
    log_text = stream.getvalue()
    expected = (
        "req=req-1 tp_rank=1 terminal=load_back_not_ready "
        "decision=rate_limited"
    )
    if expected not in log_text:
        raise AssertionError("formatted lifecycle log is missing identity fields")
    if "evict_actual_tokens=64" not in log_text:
        raise AssertionError("formatted lifecycle log is missing eviction fields")
    if "Snapshot: caller=unit_test tp_rank=1 live=0" not in log_text:
        raise AssertionError("formatted lifecycle Snapshot is missing")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()

    source_text = args.source.read_text(encoding="utf-8")
    for marker in REQUIRED_MARKERS:
        if marker not in source_text:
            raise AssertionError(f"missing r35 marker: {marker}")
    tree = ast.parse(source_text, filename=str(args.source))
    compile(tree, str(args.source), "exec")

    layerwise_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "_FluxonHostlessLayerwiseLoad"
    )
    initializer = next(
        node
        for node in layerwise_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    if "req_id" not in {arg.arg for arg in initializer.args.args}:
        raise AssertionError("layerwise completion is not tied to req_id")

    harness_type, stream = extract_helper_class(tree)
    validate_helpers(harness_type, stream)
    print("e44 r35 load-back observation validation: passed")


if __name__ == "__main__":
    main()
