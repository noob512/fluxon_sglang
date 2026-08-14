#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_BUILD_GPU_RELEASE="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r85_ssd_target_pull_gpu_cuda_20260725}"
export E44_BUILD_CPU_RELEASE="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r85_ssd_target_pull_cpu_host_20260725}"
export E44_BUILD_GPU_SDK="${E44_BUILD_GPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722}"
export E44_BUILD_CPU_SDK="${E44_BUILD_CPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721}"
export E44_R55_FINALIZE_ONLY="${E44_R85_FINALIZE_ONLY:-0}"

exec bash "$script_dir/build_e44_r55_planned_get_cancel_safe_releases.sh"
