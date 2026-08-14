#!/usr/bin/env bash
set -uo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_cpu}"
variant="${2:?missing E44 performance variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"

cpu_venv="${E44_HOST_CPU_VENV:-$E44_PERF_VENV_CPU}"
if [ ! -x "$cpu_venv/bin/python" ]; then
  echo "CPU Fluxon Python is unavailable: $cpu_venv/bin/python" >&2
  exit 1
fi
cpu_site_packages="$(
  "$cpu_venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)" || exit 1
if [ ! -d "$cpu_site_packages" ]; then
  echo "CPU Fluxon site-packages is unavailable: $cpu_site_packages" >&2
  exit 1
fi

log="$root/launch_e16bb_${E44_PERF_RUN_ID}_20260719.log"
rc_file="$root/launch_e16bb_${E44_PERF_RUN_ID}_20260719.rc"
: > "$log"
rm -f "$rc_file"

set +e
FLUXON_CPU_OWNER_SESSION="zth_fluxon_remote_cpu_e16bb_${E44_PERF_RUN_ID}" \
ROOT_DIR="$root" \
FLUXON_NODE0_IP="${FLUXON_NODE0_IP:-10.233.114.139}" \
FLUXON_NODE1_IP="${FLUXON_NODE1_IP:-10.233.114.138}" \
FLUXON_CPU_NODE_IP="${FLUXON_CPU_NODE_IP:-10.233.91.204}" \
FLUXON_CPU_DISABLE_OBSERVABILITY=false \
FLUXON_CPU_OWNER_DRAM_BYTES="${E44_HOST_CPU_OWNER_DRAM_BYTES:-274877906944}" \
FLUXON_CPU_RDMA_DEVICE_0=mlx5_4 \
FLUXON_CPU_RDMA_DEVICE_1=mlx5_6 \
FLUXON_CPU_SHARED_JSON_TIMEOUT=600 \
FLUXON_CPU_PYTHON_BIN="$cpu_venv/bin/python" \
FLUXON_CPU_SITE_PACKAGES="$cpu_site_packages" \
FLUXON_CPU_EXPECTED_COMMU_CORE_SHA256="$E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU" \
FLUXON_CPU_EXPECTED_RDMA_PROBE_SHA256="$E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU" \
FLUXON_CPU_USER_RPC_SYNC_HANDLER_THREAD_COUNT=8 \
RUST_LOG=info \
  bash "${E44_HOST_CPU_OWNER_SCRIPT:-$root/experiment_e16bb_rdma_numa1_20260714/start_cpu_owner_numa1.sh}" \
  >> "$log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$rc_file"
exit "$rc"
