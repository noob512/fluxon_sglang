#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_BUILD_GPU_RELEASE="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r96_ssd_early_only_gpu_cuda_20260728}"
export E44_BUILD_CPU_RELEASE="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r96_ssd_early_only_cpu_host_20260728}"
export E44_BUILD_GPU_SDK="${E44_BUILD_GPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722}"
export E44_BUILD_CPU_SDK="${E44_BUILD_CPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721}"
export E44_R93_FINALIZE_ONLY="${E44_R96_FINALIZE_ONLY:-0}"

bash "$script_dir/build_e44_r93_mixed_get_releases.sh"

for release in "$E44_BUILD_GPU_RELEASE" "$E44_BUILD_CPU_RELEASE"; do
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  grep -F 'ssd_capacity_writeback_enabled:' \
    "$release/start_gpu_stack_owner_numa1_ssd.sh" >/dev/null
  grep -F 'ssd_capacity_writeback_enabled' \
    "$release/source_kv_config.rs" >/dev/null
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

printf 'gpu_release=%s\n' "$E44_BUILD_GPU_RELEASE"
printf 'gpu_wheel_sha256=%s\n' "$(sha256sum "$E44_BUILD_GPU_RELEASE"/*.whl | awk '{print $1}')"
printf 'cpu_release=%s\n' "$E44_BUILD_CPU_RELEASE"
printf 'cpu_wheel_sha256=%s\n' "$(sha256sum "$E44_BUILD_CPU_RELEASE"/*.whl | awk '{print $1}')"
printf 'pyo3_sha256=%s\n' "$(tr -d '[:space:]' < "$E44_BUILD_GPU_RELEASE/fluxon_pyo3.abi3.so.sha256")"
