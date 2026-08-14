#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
gpu_release="${E44_BUILD_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r51_metadata_only_plan_gpu_cuda_20260723}"
cpu_release="${E44_BUILD_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r51_metadata_only_plan_cpu_host_20260723}"
gpu_sdk="${E44_BUILD_GPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722}"
cpu_sdk="${E44_BUILD_CPU_SDK:-/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721}"
wheel_name=fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl

for path in \
  /mnt/nvme0/mjq_build/push_sglang_fluxon_target \
  /mnt/nvme0/mjq_build/fluxon_pypack_rootfs \
  "$(dirname "$gpu_release")" \
  "$(dirname "$cpu_release")"
do
  test "$(findmnt -n -o SOURCE -T "$path")" = /dev/nvme0n1p3
done

test -f "$gpu_sdk/manifest.json"
test -f "$gpu_sdk/lib/libfluxon_commu_core.so"
test -f "$gpu_sdk/lib/libfluxon_rdma_probe.so"
test -f "$gpu_sdk/lib/libcudart.so.12"
test -f "$cpu_sdk/manifest.json"
test -f "$cpu_sdk/lib/libfluxon_commu_core.so"
test -f "$cpu_sdk/lib/libfluxon_rdma_probe.so"

case "${E44_BUILD_FINALIZE_ONLY:-${E44_R51_FINALIZE_ONLY:-0}}" in
  0)
    E44_R43_RELEASE_DIR="$gpu_release" \
    E44_R43_CLOSED_SDK_SOURCE="$gpu_sdk" \
      bash "$script_dir/build_e44_r43_gpu_direct_cuda_release.sh"

    E44_RELEASE_DIR="$cpu_release" \
    E44_CLOSED_SDK_SOURCE="$cpu_sdk" \
      bash "$script_dir/build_e44_r42_gpu_direct_staging_release.sh"
    ;;
  1) ;;
  *)
    echo "E44_BUILD_FINALIZE_ONLY/E44_R51_FINALIZE_ONLY must be 0 or 1" >&2
    exit 2
    ;;
esac

gpu_wheel="$gpu_release/$wheel_name"
cpu_wheel="$cpu_release/$wheel_name"
test -f "$gpu_wheel"
test -f "$cpu_wheel"

# The GPU release builder already records the exact input SDK.  Add the same
# provenance closure to the host-only release before sealing its manifest.
test -f "$gpu_release/closed_sdk_manifest.json"
test -f "$gpu_release/closed_sdk_inputs.sha256"
cmp -s "$gpu_sdk/manifest.json" "$gpu_release/closed_sdk_manifest.json"
(
  cd "$gpu_release"
  sha256sum -c closed_sdk_inputs.sha256 >/dev/null
)

install -m 0644 "$cpu_sdk/manifest.json" "$cpu_release/closed_sdk_manifest.json"
sha256sum \
  "$cpu_sdk/manifest.json" \
  "$cpu_sdk/lib/libfluxon_commu_core.so" \
  "$cpu_sdk/lib/libfluxon_rdma_probe.so" \
  > "$cpu_release/closed_sdk_inputs.sha256"
readelf -d "$cpu_sdk/lib/libfluxon_commu_core.so" \
  > "$cpu_release/closed_sdk_core.dynamic.txt"
readelf --version-info "$cpu_sdk/lib/libfluxon_commu_core.so" \
  > "$cpu_release/closed_sdk_core.versions.txt"
(
  cd "$cpu_release"
  rm -f fluxon_release.sha256
  find . -maxdepth 1 -type f ! -name fluxon_release.sha256 -printf '%P\0' \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > fluxon_release.sha256
  sha256sum -c closed_sdk_inputs.sha256 >/dev/null
)

wheel_member_sha256() {
  local wheel="$1"
  local member="$2"
  unzip -p "$wheel" "$member" | sha256sum | awk '{print $1}'
}

gpu_pyo3="$(tr -d '[:space:]' < "$gpu_release/fluxon_pyo3.abi3.so.sha256")"
cpu_pyo3="$(tr -d '[:space:]' < "$cpu_release/fluxon_pyo3.abi3.so.sha256")"
test "$gpu_pyo3" = "$cpu_pyo3"

gpu_core="$(wheel_member_sha256 "$gpu_wheel" fluxon_pyo3.libs/libfluxon_commu_core.so)"
gpu_probe="$(wheel_member_sha256 "$gpu_wheel" fluxon_pyo3.libs/libfluxon_rdma_probe.so)"
gpu_cudart="$(wheel_member_sha256 "$gpu_wheel" fluxon_pyo3.libs/libcudart.so.12)"
cpu_core="$(wheel_member_sha256 "$cpu_wheel" fluxon_pyo3.libs/libfluxon_commu_core.so)"
cpu_probe="$(wheel_member_sha256 "$cpu_wheel" fluxon_pyo3.libs/libfluxon_rdma_probe.so)"

# auditwheel intentionally rewrites ELF/RPATH, so packaged objects must not be
# compared byte-for-byte with their raw SDK inputs.  These are the sealed r50
# package hashes produced from the same GPU/CPU SDK pair and packaging tool.
test "$gpu_core" = e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
test "$gpu_probe" = e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
test "$gpu_cudart" = 5b8de0eec6b33e5f785da05d89869fdbfc58af3ae5af96d7d53a53180429dc82
test "$cpu_core" = 63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
test "$cpu_probe" = e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
! unzip -Z1 "$cpu_wheel" | grep -Eq 'libcuda|libcudart'

(
  cd "$gpu_release"
  sha256sum -c fluxon_release.sha256 >/dev/null
)
(
  cd "$cpu_release"
  sha256sum -c fluxon_release.sha256 >/dev/null
)

printf 'gpu_release=%s\n' "$gpu_release"
printf 'gpu_wheel_sha256=%s\n' "$(sha256sum "$gpu_wheel" | awk '{print $1}')"
printf 'cpu_release=%s\n' "$cpu_release"
printf 'cpu_wheel_sha256=%s\n' "$(sha256sum "$cpu_wheel" | awk '{print $1}')"
printf 'pyo3_sha256=%s\n' "$gpu_pyo3"
printf 'gpu_core_sha256=%s\n' "$gpu_core"
printf 'gpu_probe_sha256=%s\n' "$gpu_probe"
printf 'gpu_cudart_sha256=%s\n' "$gpu_cudart"
printf 'cpu_core_sha256=%s\n' "$cpu_core"
printf 'cpu_probe_sha256=%s\n' "$cpu_probe"
