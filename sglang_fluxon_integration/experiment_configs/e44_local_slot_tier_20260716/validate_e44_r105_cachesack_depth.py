#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path

from validate_e44_r61_tp_execute_commit import (
    R55_SCHEDULER_SHA256,
    class_method,
    validate_frozen_file,
    validate_runtime,
)
from validate_e44_r92_gdr_off_parallel_backing import validate_gdr_off_delta


R105_ADAPTER_SHA256 = "4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e"


def validate_content_depth_adapter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    depth_method = ast.unparse(
        class_method(tree, "HiCacheFluxon", "_absolute_content_depths")
    )
    put_method = ast.unparse(
        class_method(tree, "HiCacheFluxon", "local_fast_put_start")
    )
    local_only_method = ast.unparse(
        class_method(tree, "HiCacheFluxon", "local_fast_put_start_local_only")
    )
    for marker in (
        "prefix_pages = len(prefix_hashes)",
        "prefix_pages + index",
        "return None",
    ):
        if marker not in depth_method:
            raise AssertionError(f"r105 depth derivation is missing {marker}")
    for method_source in (put_method, local_only_method):
        for marker in (
            "self._absolute_content_depths(storage_keys, extra_info)",
            "content_depths=content_depths",
        ):
            if marker not in method_source:
                raise AssertionError(f"r105 Put path is missing {marker}")
    validate_frozen_file(path, R105_ADAPTER_SHA256, "adapter")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    parser.add_argument("scheduler", type=Path)
    args = parser.parse_args()

    validate_runtime(args.runtime)
    validate_gdr_off_delta(args.runtime)
    validate_content_depth_adapter(args.adapter)
    validate_frozen_file(args.scheduler, R55_SCHEDULER_SHA256, "scheduler")
    print("e44 r105 CacheSack depth validation: passed")


if __name__ == "__main__":
    main()
