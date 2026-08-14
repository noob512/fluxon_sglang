#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
repo="$workspace/Fluxon"
helpers="$workspace/experiment_configs/e16ay_get_target_pressure_shrink_20260713"
experiment="$workspace/experiment_configs/e44_local_slot_tier_20260716"
sdk=/mnt/ceph/zyc/fluxon_closed/fluxon_release_e16bk37_batch_append_20260715/closed_sdk
base="$repo/fluxon_release_e16bk30_dead_protection_rollback_20260715"
seed=/mnt/nvme0/mjq_open_fluxon_pack_env/open_fluxon/projects/511ab2c2fcc9c292dafc01629d47042763a583a8c0b0518bb8c3944465a6ffab/substrates/manylinux_container/target-caches/pack_release_tcp_thread_closed_sdk/134b3060fc2aa095473846a39de8933308054baece1ffec1e6a502867dad0368
target=/mnt/nvme0/mjq_build/push_sglang_fluxon_target
rootfs=/mnt/nvme0/mjq_build/fluxon_pypack_rootfs
release=/mnt/nvme0/mjq_build/fluxon_e44_r31_source_fence_wait_20260719

test "$(findmnt -n -o SOURCE -T "$target")" = /dev/nvme0n1p3
test -d "$rootfs"
test "$(findmnt -n -o SOURCE -T "$rootfs")" = /dev/nvme0n1p3
test "$(findmnt -n -o SOURCE -T "$(dirname "$release")")" = /dev/nvme0n1p3
ulimit -n 65535
mkdir -p "$target"
rm -rf -- "$release"
mkdir -p "$release"

if [ ! -f "$target/.seed_complete" ]; then
  rsync -rltL --no-perms --no-owner --no-group \
    "$seed/.rustc_info.json" \
    "$seed/cxxpacked" \
    "$seed/native_runtime" \
    "$seed/release" \
    "$seed/vendor_runtime" \
    "$target/"
  touch "$target/.seed_complete"
fi
if [ ! -f "$target/.tool_seed_complete" ]; then
  rsync -rltL --no-perms --no-owner --no-group \
    "$seed/dagviz" \
    "$seed/downloads" \
    "$seed/maturin" \
    "$seed/meson-0.64.0" \
    "$seed/target_cache_manifest.json" \
    "$target/"
  touch "$target/.tool_seed_complete"
fi

export CARGO_TARGET_DIR="$target"
export FLUXON_CARGO_TARGET_CACHE="$target"
export FLUXON_PYPACK_ROOTFS="$rootfs"
export FLUXON_RELEASE_DIR="$release"
export FLUXON_RELEASE_BASE="$base"
export FLUXON_BUILD_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_LINK_IMMUTABLE_ASSETS=0
export CARGO_BUILD_JOBS=1

bash "$helpers/build_e16ay_release.sh"
bash "$helpers/finalize_e16ay_release.sh"

install -m 0644 \
  "$experiment/sglang_r12_metadata_host/memory_pool_host.py" \
  "$release/memory_pool_host_fluxon_metadata_only.py"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/external_client_api/delete_ack_batch.rs" \
  "$release/source_external_delete_ack_batch.rs"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/client_kv_api/external_api.rs" \
  "$release/source_client_external_api.rs"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/client_kv_api/mod.rs" \
  "$release/source_client_mod.rs"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/client_kv_api/reclaim.rs" \
  "$release/source_client_reclaim.rs"

(
  cd "$repo"
  git rev-parse HEAD > "$release/source_head.txt"
  git status --short > "$release/source_status.txt"
  git diff --binary > "$release/source_worktree.diff"
  find fluxon_rs/fluxon_kv fluxon_rs/moka fluxon_rs/fluxon_util -type f \
    ! -path '*/target/*' \
    -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum
) > "$release/source_files.sha256"

python3 - "$release" <<'PY'
from pathlib import Path
import hashlib
import sys
import zipfile

release = Path(sys.argv[1])
wheels = sorted(p for p in release.glob("fluxon-*.whl") if "pyo3" not in p.name)
if len(wheels) != 1:
    raise SystemExit(f"expected one unified Fluxon wheel, got {[p.name for p in wheels]}")
wheel = wheels[0]
with zipfile.ZipFile(wheel) as zf:
    matches = [n for n in zf.namelist() if n.endswith("fluxon_pyo3/fluxon_pyo3.abi3.so")]
    if len(matches) != 1:
        raise SystemExit(f"expected one pyo3 abi3 so in wheel, got {matches}")
    pyo3_bytes = zf.read(matches[0])
sha = hashlib.sha256(pyo3_bytes).hexdigest()
(release / "fluxon_pyo3.abi3.so.sha256").write_text(sha + "\n")
print(f"pyo3_sha256 {sha}")
PY

(
  cd "$release"
  sha256sum \
    memory_pool_host_fluxon_metadata_only.py \
    source_files.sha256 \
    source_head.txt \
    source_status.txt \
    source_worktree.diff \
    source_external_delete_ack_batch.rs \
    source_client_external_api.rs \
    source_client_mod.rs \
    source_client_reclaim.rs \
    fluxon_pyo3.abi3.so.sha256 \
    >> fluxon_release.sha256
  sha256sum -c fluxon_release.sha256
)

find "$release" -maxdepth 1 -type f -name '*.whl' -exec sha256sum {} +
