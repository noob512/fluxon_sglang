#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="$(cd "$script_dir/../.." && pwd)"
source_repo="${E44_BUILD_SOURCE_REPO:-/mnt/nvme0/mjq_build/Fluxon_remerge_pre_ssd_20260729}"
gpu_release="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r97_native_ssd_remerge_gpu_cuda_20260729}"
cpu_release="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r97_native_ssd_remerge_cpu_host_20260729}"
gpu_sdk="${E44_BUILD_GPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722}"
cpu_sdk="${E44_BUILD_CPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721}"
base_release="${E44_RELEASE_BASE_SOURCE:-$workspace/Fluxon/fluxon_release_e16bk30_dead_protection_rollback_20260715}"
cpu_ssd_launcher=/mnt/nvme0/mjq_build/fluxon_e44_r96_ssd_early_only_cpu_host_20260728/start_cpu_owner_numa1_ssd.sh
gpu_ssd_launcher=/mnt/nvme0/mjq_build/fluxon_e44_r96_ssd_early_only_gpu_cuda_20260728/start_gpu_stack_owner_numa1_ssd.sh
expected_source_commit="${E44_BUILD_EXPECTED_SOURCE_COMMIT:-b573c810a16bc0904d4a787e8635eeeb071b6280}"

test "$(git -C "$source_repo" rev-parse HEAD)" = "$expected_source_commit"
test -z "$(git -C "$source_repo" status --porcelain)"
for path in "$gpu_release" "$cpu_release" /mnt/nvme0/mjq_build/push_sglang_fluxon_target; do
  test "$(findmnt -n -o SOURCE -T "$(dirname "$path")")" = /dev/nvme0n1p3
done
test -x "$cpu_ssd_launcher"
test -x "$gpu_ssd_launcher"

build_one() {
  local release="$1"
  local sdk="$2"
  E44_BUILD_SOURCE_REPO="$source_repo" \
  FLUXON_SOURCE_REPO="$source_repo" \
  E44_RELEASE_BASE_SOURCE="$base_release" \
  E44_RELEASE_DIR="$release" \
  E44_CLOSED_SDK_SOURCE="$sdk" \
    bash "$script_dir/build_e44_r38_get_prefix_reuse_release.sh"

  install -m 0755 "$cpu_ssd_launcher" "$release/start_cpu_owner_numa1_ssd.sh"
  install -m 0755 "$gpu_ssd_launcher" "$release/start_gpu_stack_owner_numa1_ssd.sh"
  install -m 0644 "$workspace/AGENTS.md" "$release/source_workspace_agents.md"
  install -m 0644 "$workspace/fluxon_kv_单KV容量驱逐修改总账_20260718.md" "$release/source_change_ledger.md"
  install -m 0644 "$source_repo/fluxon_rs/fluxon_kv/src/kv_ssd_storage.rs" "$release/source_kv_ssd_storage.rs"
  if [ -f "$source_repo/fluxon_rs/fluxon_kv/src/kv_ssd_storage_foyer.rs" ]; then
    install -m 0644 "$source_repo/fluxon_rs/fluxon_kv/src/kv_ssd_storage_foyer.rs" "$release/source_kv_ssd_storage_foyer.rs"
  fi
  install -m 0644 "$source_repo/fluxon_rs/fluxon_kv/src/config.rs" "$release/source_kv_config.rs"
  printf '%s\n' "$expected_source_commit" > "$release/source_merge_commit.txt"
  (
    cd "$release"
    rm -f fluxon_release.sha256
    find . -type f ! -name fluxon_release.sha256 -printf '%P\0' \
      | LC_ALL=C sort -z \
      | xargs -0 sha256sum > fluxon_release.sha256
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
}

build_one "$gpu_release" "$gpu_sdk"
build_one "$cpu_release" "$cpu_sdk"

wheel_name="$(find "$gpu_release" -maxdepth 1 -type f -name '*.whl' ! -name 'fluxon_pyo3-*' -printf '%f\n')"
test -n "$wheel_name"
test -f "$cpu_release/$wheel_name"
gpu_pyo3="$(tr -d '[:space:]' < "$gpu_release/fluxon_pyo3.abi3.so.sha256")"
cpu_pyo3="$(tr -d '[:space:]' < "$cpu_release/fluxon_pyo3.abi3.so.sha256")"
test "$gpu_pyo3" = "$cpu_pyo3"

printf 'gpu_release=%s\n' "$gpu_release"
printf 'cpu_release=%s\n' "$cpu_release"
printf 'wheel_name=%s\n' "$wheel_name"
printf 'gpu_wheel_sha256=%s\n' "$(sha256sum "$gpu_release/$wheel_name" | awk '{print $1}')"
printf 'cpu_wheel_sha256=%s\n' "$(sha256sum "$cpu_release/$wheel_name" | awk '{print $1}')"
printf 'pyo3_sha256=%s\n' "$gpu_pyo3"
