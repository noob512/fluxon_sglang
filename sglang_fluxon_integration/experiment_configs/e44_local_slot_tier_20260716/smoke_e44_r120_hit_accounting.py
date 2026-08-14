#!/usr/bin/env python3
import argparse
import importlib.util
import sys
from pathlib import Path


def load_req(schedule_batch: Path | None):
    if schedule_batch is None:
        from sglang.srt.managers.schedule_batch import Req

        return Req

    module_name = "sglang.srt.managers.schedule_batch_r120_smoke"
    spec = importlib.util.spec_from_file_location(module_name, schedule_batch)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {schedule_batch}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.Req


def make_req(req_type):
    req = req_type.__new__(req_type)
    req.rid = "r120-smoke"
    req.host_hit_length = 0
    req.host_local_hit_length = 0
    req.host_remote_hit_length = 0
    req.storage_hit_length = 0
    req.storage_candidate_hit_length = 0
    req.cached_tokens = 0
    req.already_computed = 0
    req.cached_tokens_device = 0
    req.cached_tokens_host = 0
    req.cached_tokens_host_local = 0
    req.cached_tokens_host_remote = 0
    req.cached_tokens_storage = 0
    req._cache_breakdown_computed = False
    return req


def account(req, tokens: int) -> None:
    req.cached_tokens += tokens
    req.account_cached_tokens_by_source(tokens)
    assert req.cached_tokens == (
        req.cached_tokens_device
        + req.cached_tokens_host
        + req.cached_tokens_storage
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-batch", type=Path)
    args = parser.parse_args()
    req_type = load_req(args.schedule_batch)

    # Exact shape seen in r119: the first 5,120 tokens were already on device;
    # 34,304 storage-loaded tokens became visible in a later chunk.
    req = make_req(req_type)
    req.storage_candidate_hit_length = 34_304
    req.record_storage_hit_tokens(34_304)
    req.record_storage_hit_tokens(0)
    account(req, 5_120)
    account(req, 34_304)
    assert req.storage_hit_length == 34_304
    assert req.cached_tokens_device == 5_120
    assert req.cached_tokens_host == 0
    assert req.cached_tokens_storage == 34_304

    # A first-chunk mix remains split into device, L2 host and confirmed L3.
    req = make_req(req_type)
    req.host_hit_length = 60
    req.host_local_hit_length = 20
    req.storage_candidate_hit_length = 40
    req.record_storage_hit_tokens(40)
    account(req, 100)
    assert req.cached_tokens_device == 40
    assert req.cached_tokens_host == 20
    assert req.cached_tokens_host_local == 20
    assert req.cached_tokens_storage == 40

    # Unconfirmed storage metadata cannot create L3 credit or break conservation.
    req = make_req(req_type)
    req.host_hit_length = 64
    req.storage_candidate_hit_length = 64
    account(req, 64)
    assert req.cached_tokens_device == 64
    assert req.cached_tokens_storage == 0

    print("r120 hit-accounting smoke passed")


if __name__ == "__main__":
    main()
