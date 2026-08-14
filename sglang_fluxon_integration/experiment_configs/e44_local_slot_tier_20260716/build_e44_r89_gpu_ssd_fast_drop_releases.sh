#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$script_dir/../../Fluxon"

export E44_BUILD_GPU_RELEASE="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r89_gpu_ssd_fast_drop_gpu_cuda_20260725}"
export E44_BUILD_CPU_RELEASE="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r89_gpu_ssd_fast_drop_cpu_host_20260725}"
export E44_BUILD_GPU_SDK="${E44_BUILD_GPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722}"
export E44_BUILD_CPU_SDK="${E44_BUILD_CPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721}"
export E44_R55_FINALIZE_ONLY="${E44_R89_FINALIZE_ONLY:-0}"

bash "$script_dir/build_e44_r55_planned_get_cancel_safe_releases.sh"

for release in "$E44_BUILD_GPU_RELEASE" "$E44_BUILD_CPU_RELEASE"; do
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/master_kv_router/msg_pack.rs" \
    "$release/source_master_msg_pack.rs"
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/master_kv_router/reclaim.rs" \
    "$release/source_master_reclaim.rs"
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/client_kv_api/put.rs" \
    "$release/source_client_put.rs"
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/client_kv_api/mod.rs" \
    "$release/source_client_mod.rs"
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/kv_ssd_storage.rs" \
    "$release/source_kv_ssd_storage.rs"
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/config.rs" \
    "$release/source_kv_config.rs"
  install -m 0644 \
    "$repo/fluxon_py/config.py" \
    "$release/source_python_config.py"
  (
    cd "$release"
    rm -f fluxon_release.sha256
    find . -maxdepth 1 -type f ! -name fluxon_release.sha256 -printf '%P\0' \
      | LC_ALL=C sort -z \
      | xargs -0 sha256sum > fluxon_release.sha256
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

printf 'gpu_release=%s\n' "$E44_BUILD_GPU_RELEASE"
printf 'gpu_wheel_sha256=%s\n' "$(sha256sum "$E44_BUILD_GPU_RELEASE"/*.whl | awk '{print $1}')"
printf 'cpu_release=%s\n' "$E44_BUILD_CPU_RELEASE"
printf 'cpu_wheel_sha256=%s\n' "$(sha256sum "$E44_BUILD_CPU_RELEASE"/*.whl | awk '{print $1}')"
printf 'pyo3_sha256=%s\n' "$(tr -d '[:space:]' < "$E44_BUILD_GPU_RELEASE/fluxon_pyo3.abi3.so.sha256")"
