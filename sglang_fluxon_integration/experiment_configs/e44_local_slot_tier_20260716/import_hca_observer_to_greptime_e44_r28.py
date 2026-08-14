#!/usr/bin/env python3
"""Import raw HCA samples into Greptime while preserving their original timestamps."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


TABLE = "fluxon_hca_port_timeseries"
DATA_UNIT_BYTES = 4.0


def sql_string(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_number(value: object | None) -> str:
    if value is None:
        return "NULL"
    number = float(value)
    return repr(number) if math.isfinite(number) else "NULL"


def sql_integer(value: object | None) -> str:
    return "NULL" if value is None else str(int(value))


def sql_timestamp_ns(wall_ns: int) -> str:
    timestamp = dt.datetime.fromtimestamp(wall_ns / 1e9, tz=dt.timezone.utc)
    return sql_string(timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])


def chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def execute(endpoint: str, sql: str, timeout_s: float) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/v1/sql?" + urllib.parse.urlencode({"db": "public"})
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({"sql": sql}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = response.read().decode("utf-8", "replace")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Greptime HTTP {exc.code}: {detail[:4000]}") from exc


def load_rows(path: Path, run_id: str) -> tuple[list[tuple[Any, ...]], dict[str, Any]]:
    metadata: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            if record.get("type") == "metadata":
                metadata = record
            elif record.get("type") == "sample":
                samples.append(record)

    capacities = {
        str(item.get("hca")): item.get("rate_gbps") for item in metadata.get("ports", [])
    }
    previous: dict[str, dict[str, Any]] = {}
    rows: list[tuple[Any, ...]] = []
    error_count = 0
    for record in samples:
        for item in record.get("hcas", []):
            hca = str(item.get("hca"))
            counters = item.get("counters") or {}
            prior = previous.get(hca)
            rx_gbps = None
            tx_gbps = None
            if prior is not None and counters:
                prior_counters = prior.get("counters") or {}
                duration_s = (
                    int(item.get("monotonic_start_ns", 0))
                    - int(prior.get("monotonic_start_ns", 0))
                ) / 1e9
                rx_delta = int(counters.get("PortRcvData", 0)) - int(
                    prior_counters.get("PortRcvData", 0)
                )
                tx_delta = int(counters.get("PortXmitData", 0)) - int(
                    prior_counters.get("PortXmitData", 0)
                )
                if duration_s > 0 and rx_delta >= 0 and tx_delta >= 0:
                    rx_gbps = rx_delta * DATA_UNIT_BYTES * 8.0 / duration_s / 1e9
                    tx_gbps = tx_delta * DATA_UNIT_BYTES * 8.0 / duration_s / 1e9
            error = str(item.get("error") or "")
            if error:
                error_count += 1
            rows.append(
                (
                    int(item.get("wall_mid_ns", 0)),
                    run_id,
                    metadata.get("node", ""),
                    metadata.get("hostname", ""),
                    hca,
                    str(item.get("port", "")),
                    capacities.get(hca),
                    rx_gbps,
                    tx_gbps,
                    counters.get("PortRcvData"),
                    counters.get("PortXmitData"),
                    counters.get("PortRcvPkts"),
                    counters.get("PortXmitPkts"),
                    counters.get("PortXmitWait"),
                    item.get("query_duration_ms"),
                    error,
                )
            )
            previous[hca] = item
    return rows, {
        "path": str(path),
        "node": metadata.get("node"),
        "sample_records": len(samples),
        "rows": len(rows),
        "errors": error_count,
    }


def insert_sql(rows: list[tuple[Any, ...]]) -> str:
    columns = [
        "ts", "run_id", "node", "hostname", "hca", "port", "capacity_gbps",
        "rx_gbps", "tx_gbps", "port_rcv_data", "port_xmit_data",
        "port_rcv_packets", "port_xmit_packets", "port_xmit_wait",
        "query_duration_ms", "error",
    ]
    rendered_rows = []
    for row in rows:
        rendered_rows.append(
            "(" + ", ".join(
                [
                    sql_timestamp_ns(row[0]),
                    sql_string(row[1]), sql_string(row[2]), sql_string(row[3]),
                    sql_string(row[4]), sql_string(row[5]),
                    sql_number(row[6]), sql_number(row[7]), sql_number(row[8]),
                    sql_integer(row[9]), sql_integer(row[10]), sql_integer(row[11]),
                    sql_integer(row[12]), sql_integer(row[13]), sql_number(row[14]),
                    sql_string(row[15]),
                ]
            ) + ")"
        )
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    return f'INSERT INTO "{TABLE}" ({quoted_columns}) VALUES ' + ", ".join(rendered_rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--run-id", default="e44_r28_r22_netobs_replay")
    parser.add_argument("--endpoint", default="http://127.0.0.1:4010")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    args = parser.parse_args()

    all_rows: list[tuple[Any, ...]] = []
    inputs = []
    for path in args.inputs:
        rows, summary = load_rows(path, args.run_id)
        all_rows.extend(rows)
        inputs.append(summary)
    inserted = 0
    for batch in chunks(all_rows, args.batch_size):
        execute(args.endpoint, insert_sql(batch), args.timeout_s)
        inserted += len(batch)
    count_result = execute(
        args.endpoint,
        f'SELECT COUNT(*) AS "rows" FROM "{TABLE}" WHERE "run_id"={sql_string(args.run_id)}',
        args.timeout_s,
    )
    print(
        json.dumps(
            {"run_id": args.run_id, "inputs": inputs, "inserted": inserted, "count": count_result},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
