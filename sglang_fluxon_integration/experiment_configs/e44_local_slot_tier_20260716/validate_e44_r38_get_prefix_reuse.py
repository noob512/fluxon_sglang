#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path


REQUIRED_MARKERS = (
    "Fluxon hostless prefetch reusing first handle for TP common prefix:",
    'observation["prefetch_decision"] = "tp_common_prefix_reused"',
    '"submitted_after_tp_prefix_reuse"',
    "consume_prefix_len=len(operation.hash_value)",
)

FORBIDDEN_MARKERS = (
    "prefetch_tp_transferable_page_mismatch_retry",
    "Fluxon hostless TP common-prefix retry failed",
    "tp_common_prefix_retry_mismatch",
    '"submitted_after_tp_retry"',
    "SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL",
)


def class_method(tree: ast.Module, name: str) -> ast.FunctionDef:
    cache_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UnifiedRadixCache"
    )
    return next(
        node
        for node in cache_class.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def named_calls(method: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    ]


def named_class_method(
    tree: ast.Module, class_name: str, method_name: str
) -> ast.FunctionDef:
    target_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in target_class.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def validate_prefetch_start_count(tree: ast.Module) -> None:
    method = class_method(tree, "prefetch_from_storage")
    get_start_calls = named_calls(method, "get_start")
    if len(get_start_calls) != 2:
        raise AssertionError(
            "r38 must have one KV Start and one optional Mamba Start; "
            f"found {len(get_start_calls)} get_start calls"
        )

    key_lengths: list[int] = []
    for call in get_start_calls:
        if not call.args:
            raise AssertionError("get_start call is missing its key argument")
        first_arg = call.args[0]
        if isinstance(first_arg, ast.List):
            key_lengths.append(len(first_arg.elts))
    if key_lengths != [1]:
        raise AssertionError(
            "the only literal-key get_start must be the single Mamba key: "
            f"literal lengths={key_lengths}"
        )


def validate_transfer_consumes_selected_prefix(tree: ast.Module) -> None:
    method = class_method(tree, "check_prefetch_progress")
    calls = named_calls(method, "get_transfer")
    if len(calls) != 2:
        raise AssertionError(
            f"expected KV and Mamba get_transfer calls, found {len(calls)}"
        )
    consume_calls = [
        call
        for call in calls
        if any(keyword.arg == "consume_prefix_len" for keyword in call.keywords)
    ]
    if len(consume_calls) != 1:
        raise AssertionError(
            "exactly the KV get_transfer call must carry consume_prefix_len"
        )
    keyword = next(
        keyword
        for keyword in consume_calls[0].keywords
        if keyword.arg == "consume_prefix_len"
    )
    if not (
        isinstance(keyword.value, ast.Call)
        and isinstance(keyword.value.func, ast.Name)
        and keyword.value.func.id == "len"
        and len(keyword.value.args) == 1
        and isinstance(keyword.value.args[0], ast.Attribute)
        and keyword.value.args[0].attr == "hash_value"
    ):
        raise AssertionError(
            "KV get_transfer must consume len(operation.hash_value)"
        )


def validate_adapter_contract(adapter: Path) -> None:
    source_text = adapter.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(adapter))
    compile(tree, str(adapter), "exec")
    method = named_class_method(tree, "HiCacheFluxon", "get_transfer")

    if [arg.arg for arg in method.args.kwonlyargs] != ["consume_prefix_len"]:
        raise AssertionError(
            "HiCacheFluxon.get_transfer must expose only keyword-only "
            "consume_prefix_len"
        )
    if len(method.args.kw_defaults) != 1 or not (
        isinstance(method.args.kw_defaults[0], ast.Constant)
        and method.args.kw_defaults[0].value is None
    ):
        raise AssertionError("adapter consume_prefix_len must default to None")

    store_calls = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_transfer"
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
        and node.func.value.attr == "store"
    ]
    if len(store_calls) != 1:
        raise AssertionError(
            "adapter must call self.store.get_transfer exactly once; "
            f"found {len(store_calls)}"
        )
    keywords = {keyword.arg: keyword.value for keyword in store_calls[0].keywords}
    forwarded = keywords.get("consume_prefix_len")
    if not isinstance(forwarded, ast.Name) or forwarded.id != "consume_prefix_len":
        raise AssertionError(
            "adapter must forward consume_prefix_len unchanged to the store"
        )
    if "concurrency" not in keywords:
        raise AssertionError("adapter must preserve the existing concurrency forwarding")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("adapter", type=Path)
    args = parser.parse_args()

    source_text = args.source.read_text(encoding="utf-8")
    for marker in REQUIRED_MARKERS:
        if marker not in source_text:
            raise AssertionError(f"missing r38 marker: {marker}")
    for marker in FORBIDDEN_MARKERS:
        if marker in source_text:
            raise AssertionError(f"r38 retained forbidden r36/retry marker: {marker}")

    tree = ast.parse(source_text, filename=str(args.source))
    compile(tree, str(args.source), "exec")
    validate_prefetch_start_count(tree)
    validate_transfer_consumes_selected_prefix(tree)
    validate_adapter_contract(args.adapter)
    print("e44 r38 Get common-prefix reuse and adapter validation: passed")


if __name__ == "__main__":
    main()
