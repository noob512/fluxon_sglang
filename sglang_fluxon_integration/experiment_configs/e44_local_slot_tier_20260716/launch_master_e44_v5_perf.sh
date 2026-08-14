#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
variant="${2:?missing E44 performance variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"

work="$root/services/master_work_${E44_PERF_RUN_ID}_20260718"
config="$script_dir/$E44_PERF_MASTER_CONFIG"
node0_ip="${FLUXON_NODE0_IP:-10.233.114.139}"
log="$root/log/current_cpu_remote_20260710/master_${E44_PERF_RUN_ID}_20260718.log"

rm -rf "$work"
mkdir -p "$work" "$(dirname "$log")"
: > "$log"
runtime_config="$work/master_config.runtime.yaml"
ssd_read_source_policy="${E44_PERF_SSD_READ_SOURCE_POLICY:-}"
local_ssd_early_content_max_depth="${E44_PERF_LOCAL_SSD_EARLY_CONTENT_MAX_DEPTH:-}"
post_read_remote_policy="${E44_PERF_POST_READ_REMOTE_POLICY:-}"
master_rdma_device_names="${E44_PERF_MASTER_RDMA_DEVICE_NAMES:-}"
master_tcp_control_lane_count="${E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT:-}"
if grep -F '__E44_SSD_READ_SOURCE_POLICY__' "$config" >/dev/null; then
  case "$ssd_read_source_policy" in
    legacy_remote_first | local_ssd_only_first) ;;
    *)
      echo "master config template requires a valid E44_PERF_SSD_READ_SOURCE_POLICY" >&2
      exit 2
      ;;
  esac
elif [ -n "$ssd_read_source_policy" ]; then
  echo "SSD read source policy was set for a master config without its template token" >&2
  exit 2
fi
local_ssd_early_content_gate=
if grep -F '__E44_LOCAL_SSD_EARLY_CONTENT_GATE__' "$config" >/dev/null; then
  if [ -n "$local_ssd_early_content_max_depth" ]; then
    if [[ ! "$local_ssd_early_content_max_depth" =~ ^[0-9]+$ ]] ||
       [ "$local_ssd_early_content_max_depth" -gt 4294967295 ]; then
      echo "local SSD early content max depth must be an unsigned 32-bit integer" >&2
      exit 2
    fi
    local_ssd_early_content_gate="local_ssd_early_content_max_depth: $local_ssd_early_content_max_depth"
  fi
elif [ -n "$local_ssd_early_content_max_depth" ]; then
  echo "local SSD early content depth was set for a master config without its template token" >&2
  exit 2
fi
if grep -F '__E44_POST_READ_REMOTE_POLICY__' "$config" >/dev/null; then
  case "$post_read_remote_policy" in
    retain | drop) ;;
    *)
      echo "master config template requires retain or drop post-read remote policy" >&2
      exit 2
      ;;
  esac
elif [ -n "$post_read_remote_policy" ]; then
  echo "post-read remote policy was set for a master config without its template token" >&2
  exit 2
fi
master_rdma_device_names_yaml=
if grep -F '__E44_MASTER_RDMA_DEVICE_NAMES__' "$config" >/dev/null; then
  case "$master_rdma_device_names" in
    "") ;;
    mlx5_4,mlx5_6)
      master_rdma_device_names_yaml='rdma_device_names: ["mlx5_4", "mlx5_6"]'
      ;;
    *)
      echo "unsupported master RDMA device set: $master_rdma_device_names" >&2
      exit 2
      ;;
  esac
elif [ -n "$master_rdma_device_names" ]; then
  echo "master RDMA devices were set for a config without its template token" >&2
  exit 2
fi
master_tcp_control_lane_count_yaml=
if grep -F '__E44_MASTER_TCP_CONTROL_LANE_COUNT__' "$config" >/dev/null; then
  case "$master_tcp_control_lane_count" in
    "") ;;
    8)
      master_tcp_control_lane_count_yaml='tcp_thread_control_lane_count: 8'
      ;;
    *)
      echo "unsupported master TCP control lane count: $master_tcp_control_lane_count" >&2
      exit 2
      ;;
  esac
elif [ -n "$master_tcp_control_lane_count" ]; then
  echo "master TCP control lane count was set for a config without its template token" >&2
  exit 2
fi
sed \
  -e "s/10\\.233\\.114\\.139/${node0_ip}/g" \
  -e "s/__E44_SSD_READ_SOURCE_POLICY__/${ssd_read_source_policy}/g" \
  -e "s/__E44_LOCAL_SSD_EARLY_CONTENT_GATE__/${local_ssd_early_content_gate}/g" \
  -e "s/__E44_POST_READ_REMOTE_POLICY__/${post_read_remote_policy}/g" \
  -e "s/__E44_MASTER_RDMA_DEVICE_NAMES__/${master_rdma_device_names_yaml}/g" \
  -e "s/__E44_MASTER_TCP_CONTROL_LANE_COUNT__/${master_tcp_control_lane_count_yaml}/g" \
  -e "s/__E44_RUN_ID__/${E44_PERF_RUN_ID}/g" \
  "$config" > "$runtime_config"
if [ "$node0_ip" != 10.233.114.139 ] && grep -F '10.233.114.139' "$runtime_config" >/dev/null; then
  echo "master config still contains stale node0 address" >&2
  exit 1
fi
if grep -F '__E44_SSD_READ_SOURCE_POLICY__' "$runtime_config" >/dev/null; then
  echo "master runtime config still contains the SSD read policy template token" >&2
  exit 1
fi
if grep -F '__E44_LOCAL_SSD_EARLY_CONTENT_GATE__' "$runtime_config" >/dev/null; then
  echo "master runtime config still contains the local SSD content gate template token" >&2
  exit 1
fi
if grep -F '__E44_POST_READ_REMOTE_POLICY__' "$runtime_config" >/dev/null; then
  echo "master runtime config still contains the post-read remote policy template token" >&2
  exit 1
fi
if grep -F '__E44_MASTER_RDMA_DEVICE_NAMES__' "$runtime_config" >/dev/null; then
  echo "master runtime config still contains the RDMA device template token" >&2
  exit 1
fi
if grep -F '__E44_MASTER_TCP_CONTROL_LANE_COUNT__' "$runtime_config" >/dev/null; then
  echo "master runtime config still contains the TCP control lane template token" >&2
  exit 1
fi
if [ -n "$master_rdma_device_names" ] &&
   ! grep -F 'rdma_device_names: ["mlx5_4", "mlx5_6"]' "$runtime_config" >/dev/null; then
  echo "master runtime config is missing the requested RDMA devices" >&2
  exit 1
fi
if [ -n "$master_tcp_control_lane_count" ] &&
   ! grep -F 'tcp_thread_control_lane_count: 8' "$runtime_config" >/dev/null; then
  echo "master runtime config is missing the requested TCP control lane count" >&2
  exit 1
fi
if grep -F '__E44_RUN_ID__' "$runtime_config" >/dev/null; then
  echo "master runtime config still contains the run-id template token" >&2
  exit 1
fi

export PATH="$E44_PERF_VENV_GPU/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LD_LIBRARY_PATH="$E44_PERF_VENV_GPU/lib/python3.10/site-packages/fluxon_pyo3:$E44_PERF_VENV_GPU/lib/python3.10/site-packages/fluxon_pyo3.libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
export PYTHONUNBUFFERED=1 RUST_LOG=info
cd "$work"
exec "$E44_PERF_VENV_GPU/bin/python" -m fluxon_py.runtime.start_master -c "$runtime_config" -w "$work" >> "$log" 2>&1
