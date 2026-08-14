#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$script_dir/../.." && pwd)"
repo="$workspace/Fluxon"

export E44_BUILD_GPU_RELEASE="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r93_mixed_get_gpu_cuda_20260727}"
export E44_BUILD_CPU_RELEASE="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r93_mixed_get_cpu_host_20260727}"
export E44_BUILD_GPU_SDK="${E44_BUILD_GPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722}"
export E44_BUILD_CPU_SDK="${E44_BUILD_CPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721}"
export E44_R91_FINALIZE_ONLY="${E44_R93_FINALIZE_ONLY:-0}"

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$repo/fluxon_rs/scripts/rather_no_git_submodule.py" \
  --workdir "$repo"
test "$(git -C "$repo/fluxon_rs/moka" rev-parse HEAD)" = \
  91c97076e7b1bbac306d7ace7b74f9e994440b2d

bash "$script_dir/build_e44_r91_parallel_backing_releases.sh"

moka_head="$(git -C "$repo/fluxon_rs/moka" rev-parse HEAD)"
test "$moka_head" = 91c97076e7b1bbac306d7ace7b74f9e994440b2d

for release in "$E44_BUILD_GPU_RELEASE" "$E44_BUILD_CPU_RELEASE"; do
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/external_client_api/mod.rs" \
    "$release/source_external_client_api_mod.rs"
  install -m 0644 \
    "$repo/fluxon_rs/fluxon_kv/src/master_kv_router/msg_pack.rs" \
    "$release/source_master_msg_pack.rs"
  install -m 0644 \
    "$workspace/fluxon_kv_单KV容量驱逐修改总账_20260718.md" \
    "$release/source_change_ledger.md"
  install -m 0644 \
    "$repo/setup_and_pack/rather_no_git_submodule.yaml" \
    "$release/source_rather_no_git_submodule.yaml"
  printf '%s\n' "$moka_head" > "$release/source_moka_head.txt"
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
