#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release="${E44_R43_RELEASE_DIR:-/mnt/nvme0/mjq_build/fluxon_e44_r43_gpu_direct_cuda_20260721}"
sdk="${E44_R43_CLOSED_SDK_SOURCE:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_correct_20260721}"

test "$(findmnt -n -o SOURCE -T /mnt/nvme0/mjq_build/push_sglang_fluxon_target)" = /dev/nvme0n1p3
test "$(findmnt -n -o SOURCE -T "$(dirname "$release")")" = /dev/nvme0n1p3
test -f "$sdk/manifest.json"
test -f "$sdk/lib/libfluxon_commu_core.so"
test -f "$sdk/lib/libcudart.so.12"

E44_RELEASE_DIR="$release" \
E44_CLOSED_SDK_SOURCE="$sdk" \
  bash "$script_dir/build_e44_r42_gpu_direct_staging_release.sh"

install -m 0644 "$sdk/manifest.json" "$release/closed_sdk_manifest.json"
sha256sum \
  "$sdk/manifest.json" \
  "$sdk/lib/libfluxon_commu_core.so" \
  "$sdk/lib/libfluxon_rdma_probe.so" \
  "$sdk/lib/libcudart.so.12.8.57" \
  > "$release/closed_sdk_inputs.sha256"
readelf -d "$sdk/lib/libfluxon_commu_core.so" > "$release/closed_sdk_core.dynamic.txt"
readelf --version-info "$sdk/lib/libfluxon_commu_core.so" > "$release/closed_sdk_core.versions.txt"

(
  cd "$release"
  rm -f fluxon_release.sha256
  find . -maxdepth 1 -type f ! -name fluxon_release.sha256 -printf '%P\0' \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > fluxon_release.sha256
  sha256sum -c fluxon_release.sha256
)

find "$release" -maxdepth 1 -type f -name '*.whl' -exec sha256sum {} +
cat "$release/fluxon_pyo3.abi3.so.sha256"
