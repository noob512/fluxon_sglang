#!/usr/bin/env python3
"""Expose a minimal SGLang token-id worker API in front of one vLLM server."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    import aiohttp
    from aiohttp import web
except ModuleNotFoundError:  # Pure translation tests do not require the server runtime.
    aiohttp = None
    web = None


SCHEMA = "vllm_sglang_token_adapter_v1"
MODEL_PATH = "/public/mjq/models/Qwen3-VL-8B-Instruct"
VOCAB_SIZE = 151_936
CONNECTOR_CONFIG = {
    "limit": 0,
    "ttl_dns_cache": 300,
    "force_close": True,
}
MAX_SSE_LINE_BYTES = 8 * 1024**2


class AdapterError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


async def iter_sse_data(content: Any):
    """Yield SSE data fields without aiohttp's implicit readline limit."""
    buffer = bytearray()
    async for chunk in content.iter_any():
        if not isinstance(chunk, (bytes, bytearray)):
            raise AdapterError("upstream SSE chunk is not bytes")
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                break
            if newline > MAX_SSE_LINE_BYTES:
                raise AdapterError(
                    f"upstream SSE line exceeds {MAX_SSE_LINE_BYTES} bytes"
                )
            line = bytes(buffer[:newline]).rstrip(b"\r")
            del buffer[: newline + 1]
            if line.startswith(b"data:"):
                yield line[5:].strip()
        if len(buffer) > MAX_SSE_LINE_BYTES:
            raise AdapterError(
                f"upstream SSE line exceeds {MAX_SSE_LINE_BYTES} bytes"
            )
    if buffer:
        if len(buffer) > MAX_SSE_LINE_BYTES:
            raise AdapterError(
                f"upstream SSE line exceeds {MAX_SSE_LINE_BYTES} bytes"
            )
        line = bytes(buffer).rstrip(b"\r")
        if line.startswith(b"data:"):
            yield line[5:].strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", choices=("node0", "node1"), required=True)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--upstream-base-url", required=True)
    parser.add_argument("--expected-model", default=MODEL_PATH)
    parser.add_argument("--vocab-size", type=int, default=VOCAB_SIZE)
    parser.add_argument("--request-timeout-s", type=float, default=21_600.0)
    parser.add_argument("--events-file", type=Path, required=True)
    parser.add_argument("--startup-manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    expected_port = 31_101 if args.instance == "node0" else 31_102
    expected_upstream = 31_001 if args.instance == "node0" else 31_002
    if args.listen_host != "127.0.0.1" or args.listen_port != expected_port:
        parser.error(
            f"{args.instance} requires 127.0.0.1:{expected_port}, "
            f"got {args.listen_host}:{args.listen_port}"
        )
    if args.upstream_base_url.rstrip("/") != f"http://127.0.0.1:{expected_upstream}":
        parser.error(
            f"{args.instance} requires upstream http://127.0.0.1:{expected_upstream}"
        )
    if args.expected_model != MODEL_PATH:
        parser.error(f"expected model must be {MODEL_PATH}")
    if args.vocab_size != VOCAB_SIZE:
        parser.error(f"vocab size must be {VOCAB_SIZE}")
    if args.request_timeout_s <= 0:
        parser.error("request timeout must be positive")
    if args.events_file == args.startup_manifest:
        parser.error("events and startup manifest paths must differ")
    return args


def require_int_list(value: Any, *, name: str, upper_bound: int) -> list[int]:
    if not isinstance(value, list) or not value:
        raise AdapterError(f"{name} must be a non-empty integer list")
    if any(
        isinstance(item, bool)
        or not isinstance(item, int)
        or item < 0
        or item >= upper_bound
        for item in value
    ):
        raise AdapterError(f"{name} contains an invalid token id")
    return value


def build_upstream_payload(
    request: Any, *, expected_model: str, vocab_size: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(request, dict):
        raise AdapterError("request body must be an object")
    rid = request.get("rid")
    if (
        not isinstance(rid, str)
        or not rid
        or len(rid.encode("utf-8")) > 256
    ):
        raise AdapterError("rid must be a non-empty string of at most 256 bytes")
    input_ids = require_int_list(
        request.get("input_ids"), name="input_ids", upper_bound=vocab_size
    )
    sampling = request.get("sampling_params")
    if not isinstance(sampling, dict):
        raise AdapterError("sampling_params must be an object")
    temperature = sampling.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise AdapterError("temperature must be numeric")
    max_tokens = sampling.get("max_new_tokens")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise AdapterError("max_new_tokens must be a positive integer")
    ignore_eos = sampling.get("ignore_eos")
    if ignore_eos is not True:
        raise AdapterError("ignore_eos must be true")
    if request.get("stream") is not True:
        raise AdapterError("stream must be true")
    if request.get("return_logprob") is not False:
        raise AdapterError("return_logprob must be false")
    if request.get("log_metrics") is not True:
        raise AdapterError("log_metrics must be true")

    upstream = {
        "model": expected_model,
        "prompt": input_ids,
        "request_id": rid,
        "add_special_tokens": False,
        "temperature": float(temperature),
        "max_tokens": max_tokens,
        "ignore_eos": True,
        "stream": True,
        "stream_options": {
            "include_usage": True,
            "continuous_usage_stats": True,
        },
        "return_token_ids": True,
    }
    context = {
        "rid": rid,
        "input_length": len(input_ids),
        "output_length_expected": max_tokens,
    }
    return upstream, context


@dataclass
class TranslationState:
    rid: str
    input_length: int
    output_length_expected: int
    expected_model: str
    completion_tokens: int = 0
    usage_prompt_tokens: int | None = None
    usage_completion_tokens: int | None = None
    finish_reason: str | None = None
    upstream_model: str | None = None
    upstream_request_id: str | None = None
    cached_tokens: int | None = None
    cached_tokens_details: dict[str, Any] | None = None
    adapter_error: str = ""

    def consume(self, event: Any) -> dict[str, Any] | None:
        if not isinstance(event, dict):
            raise AdapterError("upstream SSE event is not an object")
        if event.get("error") is not None:
            raise AdapterError(f"upstream streaming error: {event['error']}")
        event_id = event.get("id")
        if event_id is not None:
            expected_event_id = f"cmpl-{self.rid}"
            if event_id != expected_event_id:
                raise AdapterError(
                    "upstream request id mismatch: "
                    f"expected={expected_event_id!r} actual={event_id!r}"
                )
            self.upstream_request_id = event_id
        model = event.get("model")
        if model is not None:
            if not isinstance(model, str):
                raise AdapterError("upstream model identity is not a string")
            self.upstream_model = model

        changed = False
        choices = event.get("choices", [])
        if not isinstance(choices, list):
            raise AdapterError("upstream choices must be a list")
        for choice in choices:
            if not isinstance(choice, dict):
                raise AdapterError("upstream choice must be an object")
            token_ids = choice.get("token_ids") or []
            if not isinstance(token_ids, list) or any(
                isinstance(token, bool) or not isinstance(token, int)
                for token in token_ids
            ):
                raise AdapterError("upstream token_ids must be integers")
            if token_ids:
                self.completion_tokens += len(token_ids)
                changed = True
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None:
                self.finish_reason = str(finish_reason)
                changed = True

        usage = event.get("usage")
        if usage is not None:
            if not isinstance(usage, dict):
                raise AdapterError("upstream usage must be an object")
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            if isinstance(prompt_tokens, int):
                self.usage_prompt_tokens = prompt_tokens
            if isinstance(completion_tokens, int):
                self.usage_completion_tokens = completion_tokens
            details = usage.get("prompt_tokens_details")
            if isinstance(details, dict):
                self.cached_tokens_details = details
                cached_tokens = details.get("cached_tokens")
                if isinstance(cached_tokens, int):
                    self.cached_tokens = cached_tokens
            changed = True

        return self.sglang_event() if changed else None

    def validate(self) -> None:
        problems = []
        if self.completion_tokens != self.output_length_expected:
            problems.append(
                "completion mismatch: "
                f"expected={self.output_length_expected} actual={self.completion_tokens}"
            )
        if self.usage_prompt_tokens != self.input_length:
            problems.append(
                "prompt usage mismatch: "
                f"expected={self.input_length} actual={self.usage_prompt_tokens}"
            )
        if self.usage_completion_tokens != self.completion_tokens:
            problems.append(
                "completion usage mismatch: "
                f"stream={self.completion_tokens} usage={self.usage_completion_tokens}"
            )
        if self.upstream_model != self.expected_model:
            problems.append(
                "model mismatch: "
                f"expected={self.expected_model!r} actual={self.upstream_model!r}"
            )
        expected_event_id = f"cmpl-{self.rid}"
        if self.upstream_request_id != expected_event_id:
            problems.append(
                "request id mismatch: "
                f"expected={expected_event_id!r} actual={self.upstream_request_id!r}"
            )
        self.adapter_error = "; ".join(problems)

    def sglang_event(self) -> dict[str, Any]:
        meta = {
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
            "adapter_usage_prompt_tokens": self.usage_prompt_tokens,
            "adapter_usage_completion_tokens": self.usage_completion_tokens,
            "adapter_upstream_model": self.upstream_model,
            "adapter_upstream_request_id": self.upstream_request_id,
            "adapter_error": self.adapter_error,
        }
        if self.cached_tokens is not None:
            meta["cached_tokens"] = self.cached_tokens
        if self.cached_tokens_details is not None:
            meta["cached_tokens_details"] = self.cached_tokens_details
        return {"text": "", "meta_info": meta}


class AdapterServer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.upstream = args.upstream_base_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None
        self.events_handle: Any = None
        self.events_lock = asyncio.Lock()
        self.requests_total = 0
        self.requests_success = 0
        self.requests_error = 0
        self.inflight = 0
        self.input_tokens = 0
        self.output_tokens = 0

    async def start(self, _app: web.Application) -> None:
        for path in (self.args.events_file, self.args.startup_manifest):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise RuntimeError(f"evidence path already exists: {path}")
        timeout = aiohttp.ClientTimeout(
            total=self.args.request_timeout_s,
            connect=60,
            sock_connect=60,
            sock_read=self.args.request_timeout_s,
        )
        connector = aiohttp.TCPConnector(**CONNECTOR_CONFIG)
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        try:
            preflight = await self.upstream_preflight()
            manifest = {
                "schema": SCHEMA,
                "created_at_utc": utc_now(),
                "instance": self.args.instance,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "listen": f"http://{self.args.listen_host}:{self.args.listen_port}",
                "upstream": self.upstream,
                "expected_model": self.args.expected_model,
                "vocab_size": self.args.vocab_size,
                "request_timeout_s": self.args.request_timeout_s,
                "connector": dict(CONNECTOR_CONFIG),
                "preflight": preflight,
                "script": {
                    "path": str(Path(__file__).resolve()),
                    "sha256": sha256_file(Path(__file__).resolve()),
                },
                "python": sys.version,
                "aiohttp": aiohttp.__version__,
            }
            encoded = canonical_json_bytes(manifest) + b"\n"
            with self.args.startup_manifest.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self.events_handle = self.args.events_file.open(
                "x", encoding="utf-8", buffering=1
            )
        except Exception:
            await self.session.close()
            self.session = None
            raise

    async def stop(self, _app: web.Application) -> None:
        if self.events_handle is not None:
            self.events_handle.flush()
            os.fsync(self.events_handle.fileno())
            self.events_handle.close()
            self.events_handle = None
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def upstream_preflight(self) -> dict[str, Any]:
        assert self.session is not None
        async with self.session.get(f"{self.upstream}/health") as response:
            health_status = response.status
            await response.read()
        if health_status != 200:
            raise RuntimeError(f"upstream health failed: status={health_status}")
        async with self.session.get(f"{self.upstream}/v1/models") as response:
            models_status = response.status
            models_body = await response.json()
        model_ids = [
            item.get("id")
            for item in models_body.get("data", [])
            if isinstance(item, dict)
        ]
        if models_status != 200 or model_ids != [self.args.expected_model]:
            raise RuntimeError(
                f"upstream model identity failed: status={models_status} ids={model_ids}"
            )
        return {
            "health_status": health_status,
            "models_status": models_status,
            "model_ids": model_ids,
        }

    async def health(self, _request: web.Request) -> web.Response:
        assert self.session is not None
        try:
            async with self.session.get(f"{self.upstream}/health") as response:
                await response.read()
                status = response.status
        except Exception as exc:
            return web.Response(status=503, text=f"upstream health error: {exc}")
        return web.Response(status=200 if status == 200 else 503, text="OK")

    async def model_info(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "model_path": self.args.expected_model,
                "tokenizer_path": self.args.expected_model,
                "is_generation": True,
                "model_type": "qwen3_vl",
                "architectures": ["Qwen3VLForConditionalGeneration"],
            }
        )

    async def server_info(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "model_path": self.args.expected_model,
                "served_model_name": self.args.expected_model,
                "tp_size": 2,
                "dp_size": 1,
                "load_balance_method": "none",
                "version": SCHEMA,
                "max_total_tokens": 200_000,
                "max_running_requests": 1_024,
            }
        )

    async def models(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {
                        "id": self.args.expected_model,
                        "object": "model",
                        "owned_by": "vllm-adapter",
                    }
                ],
            }
        )

    async def metrics(self, _request: web.Request) -> web.Response:
        values = {
            "vllm_sglang_adapter_requests_total": self.requests_total,
            "vllm_sglang_adapter_requests_success_total": self.requests_success,
            "vllm_sglang_adapter_requests_error_total": self.requests_error,
            "vllm_sglang_adapter_inflight": self.inflight,
            "vllm_sglang_adapter_input_tokens_total": self.input_tokens,
            "vllm_sglang_adapter_output_tokens_total": self.output_tokens,
        }
        text = "".join(f"{name} {value}\n" for name, value in values.items())
        return web.Response(text=text, content_type="text/plain")

    async def record_event(self, value: dict[str, Any]) -> None:
        if self.events_handle is None:
            return
        encoded = canonical_json_bytes(value).decode("utf-8") + "\n"
        async with self.events_lock:
            self.events_handle.write(encoded)
            self.events_handle.flush()

    async def generate(self, request: web.Request) -> web.StreamResponse:
        started = time.monotonic()
        self.requests_total += 1
        self.inflight += 1
        state: TranslationState | None = None
        upstream_status: int | None = None
        prepared = False
        response: web.StreamResponse | None = None
        error = ""
        try:
            raw = await request.read()
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AdapterError(f"invalid JSON: {exc}") from exc
            upstream_payload, context = build_upstream_payload(
                value,
                expected_model=self.args.expected_model,
                vocab_size=self.args.vocab_size,
            )
            state = TranslationState(
                **context,
                expected_model=self.args.expected_model,
            )
            assert self.session is not None
            async with self.session.post(
                f"{self.upstream}/v1/completions",
                data=canonical_json_bytes(upstream_payload),
                headers={"Content-Type": "application/json"},
            ) as upstream_response:
                upstream_status = upstream_response.status
                if upstream_status != 200:
                    body = await upstream_response.read()
                    error = f"upstream HTTP {upstream_status}: {body[:16_384]!r}"
                    return web.Response(
                        status=upstream_status,
                        body=body,
                        content_type=upstream_response.content_type,
                    )

                response = web.StreamResponse(
                    status=200,
                    headers={"Content-Type": "text/event-stream"},
                )
                await response.prepare(request)
                prepared = True
                async for data in iter_sse_data(upstream_response.content):
                    if data == b"[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise AdapterError(f"invalid upstream SSE JSON: {exc}") from exc
                    translated = state.consume(event)
                    if translated is not None:
                        await response.write(
                            b"data: " + canonical_json_bytes(translated) + b"\n\n"
                        )

                state.validate()
                error = state.adapter_error
                await response.write(
                    b"data: " + canonical_json_bytes(state.sglang_event()) + b"\n\n"
                )
                await response.write(b"data: [DONE]\n\n")
                await response.write_eof()
                return response
        except AdapterError as exc:
            error = str(exc)
            if not prepared:
                return web.json_response(
                    {"error": {"message": error, "type": "adapter_validation_error"}},
                    status=400,
                )
            assert response is not None and state is not None
            state.adapter_error = error
            await response.write(
                b"data: " + canonical_json_bytes(state.sglang_event()) + b"\n\n"
            )
            await response.write(b"data: [DONE]\n\n")
            await response.write_eof()
            return response
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if not prepared:
                return web.json_response(
                    {"error": {"message": error, "type": "adapter_internal_error"}},
                    status=502,
                )
            assert response is not None and state is not None
            state.adapter_error = error
            await response.write(
                b"data: " + canonical_json_bytes(state.sglang_event()) + b"\n\n"
            )
            await response.write(b"data: [DONE]\n\n")
            await response.write_eof()
            return response
        finally:
            self.inflight -= 1
            success = bool(state is not None and not error and state.adapter_error == "")
            if success:
                self.requests_success += 1
                self.input_tokens += state.input_length
                self.output_tokens += state.completion_tokens
            else:
                self.requests_error += 1
            await self.record_event(
                {
                    "schema": SCHEMA,
                    "completed_at_utc": utc_now(),
                    "instance": self.args.instance,
                    "rid": state.rid if state is not None else None,
                    "input_length": state.input_length if state is not None else None,
                    "output_length_expected": (
                        state.output_length_expected if state is not None else None
                    ),
                    "completion_tokens": (
                        state.completion_tokens if state is not None else None
                    ),
                    "usage_prompt_tokens": (
                        state.usage_prompt_tokens if state is not None else None
                    ),
                    "usage_completion_tokens": (
                        state.usage_completion_tokens if state is not None else None
                    ),
                    "upstream_model": (
                        state.upstream_model if state is not None else None
                    ),
                    "upstream_request_id": (
                        state.upstream_request_id if state is not None else None
                    ),
                    "upstream_status": upstream_status,
                    "success": success,
                    "error": error or (state.adapter_error if state is not None else ""),
                    "duration_s": time.monotonic() - started,
                }
            )


def make_app(server: AdapterServer) -> web.Application:
    app = web.Application(client_max_size=512 * 1024**2)
    app.on_startup.append(server.start)
    app.on_cleanup.append(server.stop)
    app.router.add_get("/health", server.health)
    app.router.add_get("/model_info", server.model_info)
    app.router.add_get("/get_model_info", server.model_info)
    app.router.add_get("/server_info", server.server_info)
    app.router.add_get("/get_server_info", server.server_info)
    app.router.add_get("/v1/models", server.models)
    app.router.add_get("/metrics", server.metrics)
    app.router.add_post("/generate", server.generate)
    return app


async def serve(args: argparse.Namespace) -> None:
    server = AdapterServer(args)
    runner = web.AppRunner(make_app(server), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, args.listen_host, args.listen_port)
    await site.start()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    print(
        f"adapter ready instance={args.instance} "
        f"listen={args.listen_host}:{args.listen_port} upstream={args.upstream_base_url}",
        flush=True,
    )
    await stop_event.wait()
    await runner.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    if aiohttp is None or web is None:
        raise SystemExit("aiohttp is required to run the adapter")
    args = parse_args(argv)
    asyncio.run(serve(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
