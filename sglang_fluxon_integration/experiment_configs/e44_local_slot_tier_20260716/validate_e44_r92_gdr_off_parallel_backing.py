#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path

from validate_e44_r61_tp_execute_commit import (
    R55_ADAPTER_SHA256,
    R55_SCHEDULER_SHA256,
    class_method,
    validate_frozen_file,
    validate_runtime,
)


def validate_gdr_off_delta(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_FLUXON_GPU_DIRECT_STAGING_ENABLED"
            for target in node.targets
        )
    ]
    if len(assignments) != 1:
        raise AssertionError("r92 must define one immutable GDR experiment gate")
    value = assignments[0].value
    if not isinstance(value, ast.Constant) or value.value is not False:
        raise AssertionError("r92 must fail closed with GPU-direct disabled")

    init_source = ast.unparse(
        class_method(tree, "UnifiedRadixCache", "init_hicache")
    )
    prefetch_source = ast.unparse(
        class_method(tree, "UnifiedRadixCache", "prefetch_from_storage")
    )
    for marker in (
        "if _FLUXON_GPU_DIRECT_STAGING_ENABLED:",
        "self._configure_fluxon_gpu_direct_staging()",
        "Fluxon GPU-direct staging disabled: mode=cpu_h2d_only",
    ):
        if marker not in init_source:
            raise AssertionError(f"r92 init is missing GDR-off marker {marker}")
    for marker in (
        "if not _FLUXON_GPU_DIRECT_STAGING_ENABLED:",
        "gpu_admission_block_reason = 'disabled'",
        "backend.try_reserve_gpu_direct_staging",
        "backend.execute_get_plan_cpu",
        "backend.execute_get_plan_gpu",
    ):
        if marker not in prefetch_source:
            raise AssertionError(f"r92 prefetch is missing marker {marker}")
    if prefetch_source.index("if not _FLUXON_GPU_DIRECT_STAGING_ENABLED:") > prefetch_source.index(
        "backend.try_reserve_gpu_direct_staging"
    ):
        raise AssertionError("r92 must mark GDR disabled before staging admission")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    parser.add_argument("scheduler", type=Path)
    args = parser.parse_args()

    validate_runtime(args.runtime)
    validate_gdr_off_delta(args.runtime)
    validate_frozen_file(args.adapter, R55_ADAPTER_SHA256, "adapter")
    validate_frozen_file(args.scheduler, R55_SCHEDULER_SHA256, "scheduler")
    print("e44 r92 GDR-off parallel-backing validation: passed")


if __name__ == "__main__":
    main()
