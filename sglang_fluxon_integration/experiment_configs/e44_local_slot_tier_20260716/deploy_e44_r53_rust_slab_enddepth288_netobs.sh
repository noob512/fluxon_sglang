#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r53_rust_slab_gpu_cuda_20260723
export E44_DEPLOY_CPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r53_rust_slab_cpu_host_20260723
export E44_DEPLOY_GPU_REMOTE_RELEASE=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r53_rust_slab_gpu_20260723
export E44_DEPLOY_CPU_REMOTE_RELEASE=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r53_rust_slab_cpu_20260723
export E44_DEPLOY_GPU_VENV=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r53-rust-slab-gpu-20260723
export E44_DEPLOY_CPU_VENV=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r53-rust-slab-cpu-20260723
export E44_DEPLOY_VARIANT=tier1_independent_005_netobs_enddepth288_gpu_direct_r53_rust_slab
export E44_DEPLOY_MASTER_CONFIG=master_config_e44_r53_rust_slab_enddepth288_netobs.yaml
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256=49679742cc74e581f502c622a9483639ada0937c51afbb9b6b72cbd1a887e848
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256=d66e5ea4d4a61cc5d1abe81b637070a3d228dd69e6d51f9b071f6183cee9f955

exec bash "$script_dir/deploy_e44_r47_gpu_direct_full_enddepth288_netobs.sh" "$@"
