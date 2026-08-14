#!/usr/bin/env python3
"""Create the workload tables with quoted identifiers and verify Greptime SQL."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


CREATE_TIMESERIES = """
CREATE TABLE IF NOT EXISTS "fluxon_inference_timeseries" (
  "ts" TIMESTAMP(3) TIME INDEX,
  "run_id" STRING,
  "workload_name" STRING,
  "phase_name" STRING,
  "phase_type" STRING,
  "policy" STRING,
  "target_node" STRING,
  "namespace" STRING,
  "node" STRING,
  "source" STRING,
  "op" STRING,
  "locality" STRING,
  "metric_name" STRING,
  "unit" STRING,
  "sample_kind" STRING,
  "value" DOUBLE,
  "extra_labels" STRING,
  PRIMARY KEY (
    "run_id", "workload_name", "phase_name", "phase_type", "policy",
    "target_node", "namespace", "node", "source", "op", "locality",
    "metric_name", "sample_kind"
  )
)
""".strip()

CREATE_PHASE_SUMMARY = """
CREATE TABLE IF NOT EXISTS "fluxon_inference_phase_summary" (
  "ts" TIMESTAMP(3) TIME INDEX,
  "run_id" STRING,
  "workload_name" STRING,
  "phase_name" STRING,
  "phase_type" STRING,
  "policy" STRING,
  "target_node" STRING,
  "namespace" STRING,
  "status" STRING,
  "timed_out" BOOLEAN,
  "field_name" STRING,
  "field_value" DOUBLE,
  "field_text" STRING,
  "summary_json" STRING,
  PRIMARY KEY (
    "run_id", "workload_name", "phase_name", "phase_type", "policy",
    "target_node", "namespace", "field_name"
  )
)
""".strip()

CREATE_HCA_TIMESERIES = """
CREATE TABLE IF NOT EXISTS "fluxon_hca_port_timeseries" (
  "ts" TIMESTAMP(3) TIME INDEX,
  "run_id" STRING,
  "node" STRING,
  "hostname" STRING,
  "hca" STRING,
  "port" STRING,
  "capacity_gbps" DOUBLE,
  "rx_gbps" DOUBLE,
  "tx_gbps" DOUBLE,
  "port_rcv_data" BIGINT,
  "port_xmit_data" BIGINT,
  "port_rcv_packets" BIGINT,
  "port_xmit_packets" BIGINT,
  "port_xmit_wait" BIGINT,
  "query_duration_ms" DOUBLE,
  "error" STRING,
  PRIMARY KEY ("run_id", "node", "hostname", "hca", "port")
)
""".strip()


def execute(endpoint: str, sql: str, timeout_s: float) -> dict[str, object]:
    url = endpoint.rstrip("/") + "/v1/sql?" + urllib.parse.urlencode({"db": "public"})
    body = urllib.parse.urlencode({"sql": sql}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = response.read().decode("utf-8", "replace")
            return {"status": response.status, "body": json.loads(payload)}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Greptime HTTP {exc.code}: {detail[:2000]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:4010")
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--wait-s", type=float, default=60.0)
    args = parser.parse_args()

    deadline = time.monotonic() + args.wait_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            execute(args.endpoint, "SELECT 1", args.timeout_s)
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        raise last_error

    results = {
        "create_timeseries": execute(args.endpoint, CREATE_TIMESERIES, args.timeout_s),
        "create_phase_summary": execute(args.endpoint, CREATE_PHASE_SUMMARY, args.timeout_s),
        "create_hca_timeseries": execute(args.endpoint, CREATE_HCA_TIMESERIES, args.timeout_s),
        "show_tables": execute(args.endpoint, "SHOW TABLES", args.timeout_s),
    }
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
