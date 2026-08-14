#!/usr/bin/env bash
set -euo pipefail

repo=/mnt/ceph/mjq/push_sglang/Fluxon
release="$repo/fluxon_release_e44_r5_get_lifecycle_20260716"
base="$repo/fluxon_release_e16bk30_dead_protection_rollback_20260715"
sdk=/mnt/ceph/zyc/fluxon_closed/fluxon_release_e16bk37_batch_append_20260715/closed_sdk

wheel="$(find "$release" -maxdepth 1 -type f -name 'fluxon-*.whl' ! -name 'fluxon_pyo3-*' -printf '%f\n')"
test -n "$wheel"
test "$(printf '%s\n' "$wheel" | wc -l)" -eq 1

rm -rf -- "$release/closed_sdk" "$release/ext_images"
rm -f -- \
  "$release/ext_images.input.sha256" \
  "$release/ext_images.tar.gz" \
  "$release/ext_images.tar.gz.input.sha256" \
  "$release/install.py" \
  "$release/pylib_src.tar.gz" \
  "$release/pylib_src.tar.gz.input.sha256" \
  "$release/fluxon_release.sha256"

cp -al -- "$sdk" "$release/closed_sdk"
cp -al -- "$base/ext_images" "$release/"
cp -al -- "$base/ext_images.input.sha256" "$release/"
cp -al -- "$base/ext_images.tar.gz" "$release/"
cp -al -- "$base/ext_images.tar.gz.input.sha256" "$release/"
cp -al -- "$base/install.py" "$release/"
cp -al -- "$base/pylib_src.tar.gz" "$release/"
cp -al -- "$base/pylib_src.tar.gz.input.sha256" "$release/"

(
  cd "$release"
  sha256sum \
    closed_sdk/lib/libfluxon_commu_core.so \
    closed_sdk/lib/libfluxon_rdma_probe.so \
    closed_sdk/manifest.json \
    closed_sdk/native/native_runtime/include/rdma_probe_c.h \
    closed_sdk/native/native_runtime/lib/libfluxon_rdma_probe.so \
    ext_images.tar.gz \
    ext_images/ext_images.sha256 \
    "$wheel" \
    pylib_src.tar.gz \
    > fluxon_release.sha256
  sha256sum -c fluxon_release.sha256
)

sha256sum "$release/$wheel"
