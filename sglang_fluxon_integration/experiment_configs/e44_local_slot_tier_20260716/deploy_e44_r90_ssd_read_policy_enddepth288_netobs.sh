#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The legacy control and strict requester-local SSD policy share one wheel.
# Deployment validates the legacy variant; the target policy is selected by
# the same sealed finite variant table at run time.
export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r90_ssd_read_policy_gpu_cuda_20260726}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r90_ssd_read_policy_cpu_host_20260726}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r90_ssd_read_policy_gpu_20260726}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r90_ssd_read_policy_cpu_20260726}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r90-ssd-read-policy-gpu-20260726}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r90-ssd-read-policy-cpu-20260726}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r90_ssd_read_legacy}"
export E44_DEPLOY_MASTER_CONFIG=master_config_e44_r90_ssd_read_policy_enddepth288_netobs.yaml.in

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test -f "$release/source_master_get.rs"
  test -f "$release/source_master_mod.rs"
  test -f "$release/source_client_get.rs"
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
