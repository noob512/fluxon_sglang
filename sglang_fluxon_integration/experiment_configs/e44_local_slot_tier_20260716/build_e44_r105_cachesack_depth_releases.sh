#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_BUILD_SOURCE_REPO="${E44_BUILD_SOURCE_REPO:-/mnt/nvme0/mjq_build/Fluxon_cachesack_depth_r105_20260731}"
export E44_BUILD_GPU_RELEASE="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r105_cachesack_depth_gpu_cuda_20260731}"
export E44_BUILD_CPU_RELEASE="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r105_cachesack_depth_cpu_host_20260731}"
export E44_BUILD_EXPECTED_SOURCE_COMMIT="${E44_BUILD_EXPECTED_SOURCE_COMMIT:-9c7dd5d174172ddf6580cc4c8777db3481a48556}"
export GIT_COMMIT_HASH="$E44_BUILD_EXPECTED_SOURCE_COMMIT"

bash "$script_dir/build_e44_r97_native_ssd_remerge_releases.sh"

for release in "$E44_BUILD_GPU_RELEASE" "$E44_BUILD_CPU_RELEASE"; do
  test "$(tr -d '[:space:]' < "$release/source_merge_commit.txt")" = \
    "$E44_BUILD_EXPECTED_SOURCE_COMMIT"
  test ! -s "$release/source_status.txt"
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

printf 'source_commit=%s\n' "$E44_BUILD_EXPECTED_SOURCE_COMMIT"
