#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r97_native_ssd_remerge_gpu_cuda_20260729}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r97_native_ssd_remerge_cpu_host_20260729}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r97_native_ssd_remerge_gpu_20260729}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r97_native_ssd_remerge_cpu_20260729}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r97-native-ssd-remerge-gpu-20260729}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-r97-native-ssd-remerge-cpu-py311-20260729}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_DEPENDENCY_SITE="${E44_DEPLOY_CPU_DEPENDENCY_SITE:-}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-31505}"
export E44_DEPLOY_WHEEL_NAME="${E44_DEPLOY_WHEEL_NAME:-fluxon_ai-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r97_native_ssd_remerge}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r97_native_ssd_enddepth288_netobs.yaml}"
expected_source_commit="${E44_DEPLOY_EXPECTED_SOURCE_COMMIT:-b573c810a16bc0904d4a787e8635eeeb071b6280}"
expected_pyo3_sha256="${E44_DEPLOY_EXPECTED_PYO3_SHA256:-291dbc31bf47f557b31ee66e9190f3860ed5aab1caa69535547f7dff2a628689}"

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test "$(tr -d '[:space:]' < "$release/source_merge_commit.txt")" = "$expected_source_commit"
  test "$(tr -d '[:space:]' < "$release/fluxon_pyo3.abi3.so.sha256")" = "$expected_pyo3_sha256"
  test -f "$release/source_kv_ssd_storage.rs"
  test -f "$release/source_kv_ssd_storage_foyer.rs"
  test -x "$release/start_cpu_owner_numa1_ssd.sh"
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  grep -F 'pub enum KvSsdStorageBackend' "$release/source_kv_config.rs" >/dev/null
  grep -F 'Self::Native' "$release/source_kv_config.rs" >/dev/null
  grep -F 'ssd_write_rate_limit_bytes_per_sec' "$release/source_kv_config.rs" >/dev/null
  grep -F 'io_uring' "$release/source_kv_ssd_storage.rs" >/dev/null
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
