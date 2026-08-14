#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_BUILD_GPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r52_owner_local_first_gpu_cuda_20260723
export E44_BUILD_CPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r52_owner_local_first_cpu_host_20260723
export E44_BUILD_GPU_SDK=/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722
export E44_BUILD_CPU_SDK=/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721
export E44_BUILD_FINALIZE_ONLY="${E44_R52_FINALIZE_ONLY:-0}"

exec bash "$script_dir/build_e44_r51_metadata_only_plan_releases.sh"
