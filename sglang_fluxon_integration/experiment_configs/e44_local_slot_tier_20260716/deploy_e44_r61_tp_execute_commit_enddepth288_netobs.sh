#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
r55_config=artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config

# r61 reuses the sealed r55 release and exact archived r55 adapter/scheduler.
# Relative to r60 it only closes the TP commit gap after Plan execution.
export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r55_planned_get_cancel_safe_gpu_cuda_20260723}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r55_planned_get_cancel_safe_cpu_host_20260723}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r55_planned_get_cancel_safe_gpu_20260723}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r55_planned_get_cancel_safe_cpu_20260723}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r61_tp_execute_commit}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml}"
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_RADIX_SOURCE="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r61_tp_execute_commit.py}"
export E44_DEPLOY_ADAPTER_SOURCE="${E44_DEPLOY_ADAPTER_SOURCE:-$r55_config/hicache_fluxon_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_SCHEDULER_SOURCE="${E44_DEPLOY_SCHEDULER_SOURCE:-$r55_config/scheduler_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_TIMELINE_VALIDATOR="${E44_DEPLOY_TIMELINE_VALIDATOR:-validate_e44_r61_tp_execute_commit.py}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4}"
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256="${E44_DEPLOY_EXPECTED_ADAPTER_SHA256:-eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd}"
export E44_DEPLOY_EXPECTED_SCHEDULER_SHA256="${E44_DEPLOY_EXPECTED_SCHEDULER_SHA256:-5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef}"

exec bash "$script_dir/deploy_e44_r47_gpu_direct_full_enddepth288_netobs.sh" "$@"
