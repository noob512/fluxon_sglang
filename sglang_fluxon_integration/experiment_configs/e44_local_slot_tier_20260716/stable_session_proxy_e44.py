#!/usr/bin/env python3
"""Deterministic owner affinity and TP1 placement for E44 experiments.

The fixed workload embeds ``agent_group:N`` in its system prompt and uses one
group per session. With two workers, even/odd groups retain the historical
48/48 owner placement. With four workers, the owner choice stays unchanged and
each owner's 48 sessions are deterministically split 24/24 across its two TP1
clients. This is an experiment control, not a production routing policy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter

from aiohttp import ClientConnectionError, ClientSession, ClientTimeout, TCPConnector, web


GROUP_RE = re.compile(r"\bagent_group:(\d+)\]")
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=32000)
    parser.add_argument(
        "--workers",
        nargs="+",
        default=["http://10.233.114.139:31001", "http://10.233.114.138:31001"],
    )
    args = parser.parse_args()
    if len(args.workers) not in (2, 4):
        parser.error("--workers requires exactly 2 or 4 endpoints")
    return args


def extract_group(body: bytes) -> int:
    payload = json.loads(body)
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("request has no messages")
    content = messages[0].get("content") if isinstance(messages[0], dict) else None
    if not isinstance(content, str):
        raise ValueError("first message content is not text")
    match = GROUP_RE.search(content)
    if match is None:
        raise ValueError("agent_group marker is absent from first message")
    group = int(match.group(1))
    if not 0 <= group < 96:
        raise ValueError(f"agent_group is outside fixed S96 workload: {group}")
    return group


def select_worker(group: int, worker_count: int) -> int:
    """Keep the historical owner choice, then split each owner across TP1 clients."""
    if not 0 <= group < 96:
        raise ValueError(f"agent_group is outside fixed S96 workload: {group}")
    if worker_count == 2:
        return group % 2
    if worker_count == 4:
        owner_index = group % 2
        client_within_owner = (group // 2) % 2
        return owner_index * 2 + client_within_owner
    raise ValueError(f"unsupported worker count: {worker_count}")


async def on_startup(app: web.Application) -> None:
    app["session"] = ClientSession(
        connector=TCPConnector(limit=256, ttl_dns_cache=300),
        timeout=ClientTimeout(total=None, connect=10, sock_read=330),
    )


async def on_cleanup(app: web.Application) -> None:
    await app["session"].close()


async def health(request: web.Request) -> web.Response:
    session: ClientSession = request.app["session"]

    async def check(worker: str) -> int:
        try:
            async with session.get(f"{worker}/health") as response:
                return response.status
        except Exception:
            return 599

    statuses = await asyncio.gather(*(check(worker) for worker in request.app["workers"]))
    status = 200 if statuses == [200] * len(request.app["workers"]) else 503
    return web.json_response(
        {"workers": statuses, "completed": dict(request.app["counts"])}, status=status
    )


async def proxy(request: web.Request) -> web.StreamResponse:
    if request.method != "POST" or request.path != "/v1/chat/completions":
        return web.Response(status=404, text="stable-session proxy only supports chat completions\n")

    started = time.perf_counter()
    body = await request.read()
    try:
        group = extract_group(body)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return web.Response(status=400, text=f"invalid fixed workload request: {exc}\n")

    worker_index = select_worker(group, len(request.app["workers"]))
    worker = request.app["workers"][worker_index]
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in HOP_BY_HOP and name.lower() != "host"
    }
    session: ClientSession = request.app["session"]
    upstream = None
    for attempt in range(2):
        try:
            upstream = await session.request(
                request.method,
                f"{worker}{request.rel_url}",
                data=body,
                headers=headers,
            )
            break
        except ClientConnectionError as exc:
            if attempt != 0:
                raise
            print(
                f"retrying group={group} worker={worker_index} "
                f"before_response error={type(exc).__name__}",
                flush=True,
            )
    assert upstream is not None
    async with upstream:
        response_headers = {
            name: value
            for name, value in upstream.headers.items()
            if name.lower() not in HOP_BY_HOP
        }
        response_headers["x-stable-session-worker"] = str(worker_index)
        downstream = web.StreamResponse(
            status=upstream.status, headers=response_headers
        )
        await downstream.prepare(request)
        async for chunk in upstream.content.iter_any():
            await downstream.write(chunk)
        await downstream.write_eof()
        status = upstream.status

    request.app["counts"][worker_index] += 1
    print(
        f"completed group={group} worker={worker_index} status={status} "
        f"elapsed_ms={(time.perf_counter() - started) * 1000:.3f} "
        f"counts={'/'.join(str(request.app['counts'][i]) for i in range(len(request.app['workers'])))}",
        flush=True,
    )
    return downstream


def main() -> None:
    args = parse_args()
    app = web.Application(client_max_size=512 * 1024 * 1024)
    app["workers"] = [worker.rstrip("/") for worker in args.workers]
    app["counts"] = Counter()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/health", health)
    app.router.add_route("*", "/{tail:.*}", proxy)
    web.run_app(app, host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
