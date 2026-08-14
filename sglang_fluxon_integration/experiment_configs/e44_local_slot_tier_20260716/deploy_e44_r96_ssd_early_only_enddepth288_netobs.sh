#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r96_ssd_early_only_gpu_cuda_20260728}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r96_ssd_early_only_cpu_host_20260728}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r96_ssd_early_only_gpu_20260728}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r96_ssd_early_only_cpu_20260728}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r96-ssd-early-only-gpu-20260728}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-r96-cpu-py311-20260728}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_DEPENDENCY_SITE="${E44_DEPLOY_CPU_DEPENDENCY_SITE:-}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-30448}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r96_ssd_early_only}"
export E44_DEPLOY_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test -f "$release/source_external_client_api_mod.rs"
  test -f "$release/source_master_msg_pack.rs"
  test -f "$release/source_change_ledger.md"
  test -f "$release/source_rather_no_git_submodule.yaml"
  test "$(tr -d '[:space:]' < "$release/source_moka_head.txt")" = 91c97076e7b1bbac306d7ace7b74f9e994440b2d
  test -f "$release/source_parallel_backing_design.md"
  test -f "$release/source_workspace_agents.md"
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  test -x "$release/start_cpu_owner_numa1_ssd.sh"
  test "$(tr -d '[:space:]' < "$release/fluxon_pyo3.abi3.so.sha256")" = 9ec5a8797c786df4a8c2b43eb43893e78f780caa7de3c5f75e330ddc77392093
  grep -F 'ssd_capacity_writeback_enabled:' \
    "$release/start_gpu_stack_owner_numa1_ssd.sh" >/dev/null
  grep -F 'ssd_capacity_writeback_enabled' \
    "$release/source_kv_config.rs" >/dev/null
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
