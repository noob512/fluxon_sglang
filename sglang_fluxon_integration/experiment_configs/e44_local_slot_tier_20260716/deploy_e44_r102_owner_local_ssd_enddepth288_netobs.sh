#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r102_owner_local_ssd_gpu_cuda_20260730}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r102_owner_local_ssd_cpu_host_20260730}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r102_owner_local_ssd_gpu_20260730}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r102_owner_local_ssd_cpu_20260730}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r102-owner-local-ssd-gpu-20260730}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-r102-owner-local-ssd-cpu-py311-20260730}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-31505}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r102_owner_local_ssd}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r102_owner_local_ssd_enddepth288_netobs.yaml}"
export E44_DEPLOY_EXPECTED_SOURCE_COMMIT="${E44_DEPLOY_EXPECTED_SOURCE_COMMIT:-c466ef68636e8b842b91b1d3ba988cab41a4f1e1}"
export E44_DEPLOY_EXPECTED_PYO3_SHA256="${E44_DEPLOY_EXPECTED_PYO3_SHA256:-c9960eb6cf2af605e323b34a8b834cde03d16536d81010c24266ab0e00b871f3}"
export E44_DEPLOY_RADIX_SOURCE="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_TIMELINE_VALIDATOR="${E44_DEPLOY_TIMELINE_VALIDATOR:-validate_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9}"

if grep -Eq 'ssd_read_source_policy|__E44_SSD_READ_SOURCE_POLICY__' \
  "$script_dir/$E44_DEPLOY_MASTER_CONFIG"; then
  echo "r102 has requester-local source order in the planner; refusing legacy SSD policy YAML" >&2
  exit 2
fi
test "$(sha256sum "$script_dir/$E44_DEPLOY_RADIX_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_RADIX_SHA256"
test "$(sha256sum "$script_dir/$E44_DEPLOY_TIMELINE_VALIDATOR" | awk '{print $1}')" = \
  c471edac35fa634178d49c32ea2e4800c912b4d562273a50d2f678dc6a8271fe

exec bash "$script_dir/deploy_e44_r97_native_ssd_remerge_enddepth288_netobs.sh" "$@"
