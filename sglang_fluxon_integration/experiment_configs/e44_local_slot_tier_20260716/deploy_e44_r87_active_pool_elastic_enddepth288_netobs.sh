#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# r87 keeps the sealed r86 SGLang workload/cache/SSD policy and changes only
# the Fluxon release plus the capacity-control experiment helper.
export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r87_active_pool_elastic_gpu_cuda_20260725}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r87_active_pool_elastic_cpu_host_20260725}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r87_active_pool_elastic_gpu_20260725}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r87_active_pool_elastic_cpu_20260725}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r87-active-pool-elastic-gpu-20260725}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r87-active-pool-elastic-cpu-20260725}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r87_active_pool_elastic}"

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test -f "$release/source_one_seg_allocator.rs"
  test -f "$release/source_master_seg_manager.rs"
  test -f "$release/source_master_placement.rs"
  test -f "$release/source_capacity_controller.py"
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  test -x "$release/start_cpu_owner_numa1_ssd.sh"
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
