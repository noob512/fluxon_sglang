#!/usr/bin/env python3
"""Dependency-free checks for the r135 partial source-admission helper."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def load_helper(source: Path):
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_fluxon_hostless_max_atomic_prefix_pages"
    )
    namespace = {"Sequence": tuple}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace[node.name]


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name(
        "unified_radix_cache_e44_r135_partial_admission.py"
    )
    helper = load_helper(source)

    # A budget that stops inside the second group must retain only the first
    # whole group; it may never split a radix node.
    assert helper(300, [10, 20, 30], 64, 25 * 64) == 10
    assert helper(300, [10, 20, 30], 64, 30 * 64) == 30
    assert helper(300, [10, 20, 30], 64, 9 * 64) == 0
    assert helper(8, [2, 3, 3], 64, 5 * 64) == 5

    # Empty group metadata is only a compatibility fallback for one-page
    # groups; a zero/negative group is a programmer error.
    assert helper(8, [], 64, 5 * 64) == 5
    try:
        helper(8, [2, 0, 3], 64, 8 * 64)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive atomic group was accepted")

    text = source.read_text(encoding="utf-8")
    assert "device_headroom_available_tokens" in text
    assert "source_admission_partial" in text
    assert "execute_get_plan_cpu" in text
    assert text.index("_fluxon_hostless_max_atomic_prefix_pages(") < text.index(
        "execute_get_plan_cpu("
    )
    ast.parse(text, filename=str(source))
    print("r135 partial source-admission helper: passed")


if __name__ == "__main__":
    main()
