#!/usr/bin/env bash
set -euo pipefail

repo=/mnt/ceph/mjq/push_sglang/Fluxon
helpers=/mnt/ceph/mjq/push_sglang/experiment_configs/e16ay_get_target_pressure_shrink_20260713
sdk=/mnt/ceph/zyc/fluxon_closed/fluxon_release_e16bk37_batch_append_20260715/closed_sdk
release="$repo/fluxon_release_e44_r5_get_lifecycle_20260716"

export FLUXON_RELEASE_DIR="$release"
export FLUXON_RELEASE_BASE="$repo/fluxon_release_e16bk30_dead_protection_rollback_20260715"
export FLUXON_BUILD_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_LINK_IMMUTABLE_ASSETS=1

rm -rf -- "$release"
mkdir -p "$release"

bash "$helpers/build_e16ay_release.sh"
bash "$helpers/finalize_e16ay_release.sh"

sha256sum \
  "$sdk/lib/libfluxon_commu_core.so" \
  "$sdk/lib/libfluxon_rdma_probe.so"
find "$release" -type f -name '*.whl' -exec sha256sum {} +
