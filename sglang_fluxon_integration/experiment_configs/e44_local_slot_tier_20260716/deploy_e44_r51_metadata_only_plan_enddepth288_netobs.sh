#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r51_metadata_only_plan_gpu_cuda_20260723
export E44_DEPLOY_CPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r51_metadata_only_plan_cpu_host_20260723
export E44_DEPLOY_GPU_REMOTE_RELEASE=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r51_metadata_only_plan_gpu_20260723
export E44_DEPLOY_CPU_REMOTE_RELEASE=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r51_metadata_only_plan_cpu_20260723
export E44_DEPLOY_GPU_VENV=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r51-metadata-only-plan-gpu-20260723
export E44_DEPLOY_CPU_VENV=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r51-metadata-only-plan-cpu-20260723
export E44_DEPLOY_VARIANT=tier1_independent_005_netobs_enddepth288_gpu_direct_r51_metadata_only_plan
export E44_DEPLOY_MASTER_CONFIG=master_config_e44_r51_metadata_only_plan_enddepth288_netobs.yaml
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256=3bdab2956a5a255423a7331c5c84dfec9f1be35b5de6b2bdd7169c8a7ed8aab7
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256=1cc7153e846ffcd9f32e11f58e55fff2c5b7725b39123b78a93de9319b33114a

exec bash "$script_dir/deploy_e44_r47_gpu_direct_full_enddepth288_netobs.sh" "$@"
