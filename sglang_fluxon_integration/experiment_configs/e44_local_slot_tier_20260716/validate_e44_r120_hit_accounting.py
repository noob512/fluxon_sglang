#!/usr/bin/env python3
import argparse
import ast
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method_source(tree: ast.Module, class_name: str, method_name: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    item.name == method_name
                ):
                    return ast.unparse(item)
    raise AssertionError(f"missing {class_name}.{method_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-batch", type=Path, required=True)
    parser.add_argument("--scheduler", type=Path, required=True)
    parser.add_argument("--schedule-batch-sha256", required=True)
    parser.add_argument("--scheduler-sha256", required=True)
    args = parser.parse_args()

    assert sha256(args.schedule_batch) == args.schedule_batch_sha256
    assert sha256(args.scheduler) == args.scheduler_sha256

    schedule_text = args.schedule_batch.read_text()
    scheduler_text = args.scheduler.read_text()
    schedule_tree = ast.parse(schedule_text)
    scheduler_tree = ast.parse(scheduler_text)

    record = method_source(schedule_tree, "Req", "record_storage_hit_tokens")
    account = method_source(schedule_tree, "Req", "account_cached_tokens_by_source")
    prepare = method_source(schedule_tree, "ScheduleBatch", "prepare_for_extend")
    consume = method_source(scheduler_tree, "Scheduler", "_get_new_batch_prefill_raw")

    assert "self.storage_hit_length += loaded_tokens" in record
    assert "loaded_tokens < 0" in record
    assert "self.storage_hit_length - self.cached_tokens_storage" in account
    assert "self.cached_tokens_storage += storage_portion" in account
    assert "self.cached_tokens_device += new_cached - storage_portion" in account
    assert "accounted != self.cached_tokens" in account
    assert "req.cached_tokens += new_cached" in prepare
    assert "req.account_cached_tokens_by_source(new_cached)" in prepare
    assert prepare.index("req.cached_tokens += new_cached") < prepare.index(
        "req.account_cached_tokens_by_source(new_cached)"
    )
    assert "req.record_storage_hit_tokens(" in consume
    assert "self.tree_cache.pop_prefetch_loaded_tokens(req.rid)" in consume
    assert "req.storage_hit_length =" not in consume

    print(
        "r120 validator passed: "
        f"schedule_batch={args.schedule_batch_sha256} "
        f"scheduler={args.scheduler_sha256}"
    )


if __name__ == "__main__":
    main()
