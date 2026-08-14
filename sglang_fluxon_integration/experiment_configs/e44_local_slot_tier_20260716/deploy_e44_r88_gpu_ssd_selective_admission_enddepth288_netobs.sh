#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# r88 keeps the sealed r87 SGLang workload, cache policy and active-capacity
# control. It changes only Fluxon's GPU-owner SSD victim filtering/admission.
export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r88_gpu_ssd_selective_admission_gpu_cuda_20260725}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r88_gpu_ssd_selective_admission_cpu_host_20260725}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r88_gpu_ssd_selective_admission_gpu_20260725}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r88_gpu_ssd_selective_admission_cpu_20260725}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r88-gpu-ssd-selective-admission-gpu-20260725}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r88-gpu-ssd-selective-admission-cpu-20260725}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r88_gpu_ssd_selective_admission}"

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test -f "$release/source_master_msg_pack.rs"
  test -f "$release/source_master_reclaim.rs"
  test -f "$release/source_client_put.rs"
  test -f "$release/source_client_mod.rs"
  test -f "$release/source_kv_ssd_storage.rs"
  test -f "$release/source_kv_config.rs"
  test -f "$release/source_python_config.py"
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  test -x "$release/start_cpu_owner_numa1_ssd.sh"
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
