#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_BUILD_SOURCE_REPO="${E44_BUILD_SOURCE_REPO:-/mnt/nvme0/mjq_build/fluxon_e44_r104_pressure_ack_src}"
export E44_BUILD_GPU_RELEASE="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r104_pressure_ack_gpu_cuda_20260731}"
export E44_BUILD_CPU_RELEASE="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r104_pressure_ack_cpu_host_20260731}"
export E44_BUILD_EXPECTED_SOURCE_COMMIT="${E44_BUILD_EXPECTED_SOURCE_COMMIT:-9e6429229ce307eea23f2d442b14946dc20ba519}"

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
