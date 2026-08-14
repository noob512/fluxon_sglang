#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_R43_RELEASE_DIR=/mnt/nvme0/mjq_build/fluxon_e44_r55_planned_get_cancel_safe_gpu_cuda_20260723
export E44_R43_SMOKE_TAG=e44_r55_planned_get_cancel_safe_gpu_cpu_mixed_smoke
export E44_R43_INSTANCE_PREFIX=e44_r55_planned_get_cancel_safe
export E44_R43_KEY=fluxon_e44_r55_planned_get_cancel_safe_remote_smoke_20260723
export E44_R43_VENV=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
export E44_R43_SSH_IDENTITY="${E44_R43_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_R43_CPU_FALLBACK_SMOKE=1
export E44_R52_MIXED_SOURCE_SMOKE=1
export E44_R54_REQUIRE_TERMINAL_TIMING=1
export E44_R55_PLANNED_CPU_STRESS=1
export E44_R55_PLANNED_CPU_STRESS_COUNT=228
export E44_R43_OWNER_DRAM_BYTES=4294967296
export E44_R43_OWNER_LOCAL_RESERVE_VALUE_LEN=4718592
export E44_R43_OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES=1358954496

exec bash "$script_dir/run_e44_r43_gpu_get_smoke.sh"
