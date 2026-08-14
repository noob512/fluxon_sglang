#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r48_gpu_direct_single_worker_gpu1_20260722
export E44_DEPLOY_CPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_full_cpu_host_20260721
export E44_DEPLOY_GPU_REMOTE_RELEASE=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r48_gpu_direct_single_worker_gpu1_enddepth288_netobs_20260722
export E44_DEPLOY_CPU_REMOTE_RELEASE=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r48_cpu_host_full_enddepth288_netobs_20260722
export E44_DEPLOY_GPU_VENV=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r48-gpu-direct-single-worker-gpu1-20260722
export E44_DEPLOY_CPU_VENV=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r48-gpu-direct-full-cpu-host-20260722
export E44_DEPLOY_VARIANT=tier1_independent_005_netobs_enddepth288_gpu_direct_r48
export E44_DEPLOY_MASTER_CONFIG=master_config_e44_r48_gpu_direct_single_worker_gpu1_enddepth288_netobs.yaml
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256=075461f1af1bf710061b4bd2ab18f7f3ceee7b9bfee8a16d16ab61e0c67e19e3

exec bash "$script_dir/deploy_e44_r47_gpu_direct_full_enddepth288_netobs.sh" "$@"
