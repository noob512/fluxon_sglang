#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# r77 changes only the Fluxon release. Reuse the r61 deployment definition for
# the sealed SGLang radix/adapter/scheduler and all workload-facing settings.
export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r77_ssd_unified_gpu_cuda_20260724}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r77_ssd_unified_cpu_host_20260724}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r77_ssd_unified_gpu_20260724}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r77_ssd_unified_cpu_20260724}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r77-ssd-unified-gpu-20260724}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r77-ssd-unified-cpu-20260724}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r77_ssd_unified}"

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test -f "$release/source_kv_ssd_storage.rs"
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  test -x "$release/start_cpu_owner_numa1_ssd.sh"
done

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
