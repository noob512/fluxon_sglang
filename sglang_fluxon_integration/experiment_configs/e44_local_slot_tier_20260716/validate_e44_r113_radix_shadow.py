#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import textwrap
from pathlib import Path
from types import SimpleNamespace

from validate_e44_r61_tp_execute_commit import (
    R55_SCHEDULER_SHA256,
    validate_frozen_file,
    validate_runtime,
)
from validate_e44_r92_gdr_off_parallel_backing import validate_gdr_off_delta


def _class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"missing {class_name}.{method_name}")


def _module_function(tree: ast.Module, function_name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"missing {function_name}")


def _load_method(method: ast.FunctionDef):
    namespace: dict[str, object] = {}
    source = (
        "from __future__ import annotations\n"
        "from typing import Any, List, Optional\n"
        "class Harness:\n"
        + textwrap.indent(ast.unparse(method), "    ")
    )
    exec(compile(source, "<radix-shadow-adapter-method>", "exec"), namespace)
    return namespace["Harness"]


def _load_function(function: ast.FunctionDef):
    namespace: dict[str, object] = {}
    source = (
        "from __future__ import annotations\n"
        "from typing import List, Optional, Tuple\n"
        + ast.unparse(function)
    )
    exec(compile(source, "<radix-shadow-wrapper-function>", "exec"), namespace)
    return namespace[function.name]


def validate_adapter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    parent_method = _class_method(tree, "HiCacheFluxon", "_radix_parent_keys")
    depth_method = _class_method(tree, "HiCacheFluxon", "_absolute_content_depths")
    parent_harness = _load_method(parent_method)()
    parent_harness._store_key = lambda key, component=None: f"{component or 'kv'}:{key}"
    depth_harness = _load_method(depth_method)

    keys = ["kv:a", "kv:b", "kv:c"]
    no_metadata = SimpleNamespace(prefix_keys=None)
    root = SimpleNamespace(prefix_keys=[])
    prefixed = SimpleNamespace(prefix_keys=["p0", "p1"])

    assert parent_harness._radix_parent_keys(keys, None) is None
    assert parent_harness._radix_parent_keys(keys, no_metadata) is None
    assert parent_harness._radix_parent_keys(keys, root) == [None, "kv:a", "kv:b"]
    assert parent_harness._radix_parent_keys(keys, prefixed, "mamba") == [
        "mamba:p1",
        "kv:a",
        "kv:b",
    ]
    assert depth_harness._absolute_content_depths(keys, root) == [0, 1, 2]
    assert depth_harness._absolute_content_depths(keys, prefixed) == [2, 3, 4]

    for method_name in (
        "local_fast_put_start",
        "local_fast_put_start_local_only",
    ):
        method_source = ast.unparse(_class_method(tree, "HiCacheFluxon", method_name))
        for marker in (
            "self._radix_parent_keys(storage_keys, extra_info, component_name)",
            "radix_parent_keys=radix_parent_keys",
            "content_depths=content_depths",
        ):
            if marker not in method_source:
                raise AssertionError(f"{method_name} is missing {marker}")

    for method_name in (
        "_put_opts_for_replica_task_mask",
        "_call_direct_local_fast_put_start",
        "_call_local_fast_put_start",
    ):
        method_source = ast.unparse(_class_method(tree, "HiCacheFluxon", method_name))
        if "radix_parent_keys" not in method_source:
            raise AssertionError(f"{method_name} does not propagate radix_parent_keys")


def validate_fluxon_python(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    validate = _load_function(_module_function(tree, "_validate_put_radix_metadata"))
    keys = ["root", "child"]
    assert validate(keys, None, None) == (None, None)
    assert validate(keys, [None, "root"], [0, 1]) == (
        [None, "root"],
        [0, 1],
    )

    invalid_cases = (
        ([None, "root"], None),
        ([None], [0]),
        (["parent", "root"], [0, 1]),
        ([None, None], [0, 1]),
        ([None, "child"], [0, 1]),
    )
    for parents, depths in invalid_cases:
        try:
            validate(keys, parents, depths)
        except ValueError:
            continue
        raise AssertionError(
            f"invalid Radix metadata was accepted: parents={parents} depths={depths}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    parser.add_argument("scheduler", type=Path)
    parser.add_argument("--fluxon-python", type=Path)
    args = parser.parse_args()
    validate_runtime(args.runtime)
    validate_gdr_off_delta(args.runtime)
    validate_adapter(args.adapter)
    validate_frozen_file(args.scheduler, R55_SCHEDULER_SHA256, "scheduler")
    if args.fluxon_python is not None:
        validate_fluxon_python(args.fluxon_python)
    print("e44 r113 Radix shadow adapter validation: passed")


if __name__ == "__main__":
    main()
