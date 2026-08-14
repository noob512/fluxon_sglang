#!/usr/bin/env bash
set -euo pipefail
root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
venv=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r4-20260716
work="$root/services/master_work_e44_r4_20260716"
config="$root/e16bk_fluxon_specific_12qps_20260714/master_config_sync8.yaml"
log="$root/log/current_cpu_remote_20260710/master_e44_r4_20260716.log"
rm -rf "$work"
mkdir -p "$work" "$(dirname "$log")"
: > "$log"
export PATH="$venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LD_LIBRARY_PATH="$venv/lib/python3.10/site-packages/fluxon_pyo3:$venv/lib/python3.10/site-packages/fluxon_pyo3.libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
export PYTHONUNBUFFERED=1 RUST_LOG=info
cd "$work"
exec "$venv/bin/python" -m fluxon_py.runtime.start_master -c "$config" -w "$work" >> "$log" 2>&1
