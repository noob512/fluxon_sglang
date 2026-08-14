#!/usr/bin/env bash
set -euo pipefail

repo=/mnt/ceph/mjq/push_sglang/Fluxon
helpers=/mnt/ceph/mjq/push_sglang/experiment_configs/e16ay_get_target_pressure_shrink_20260713
sdk=/mnt/ceph/zyc/fluxon_closed/fluxon_release_e16bk37_batch_append_20260715/closed_sdk
base="$repo/fluxon_release_e16bk30_dead_protection_rollback_20260715"
seed=/mnt/nvme0/mjq_open_fluxon_pack_env/open_fluxon/projects/511ab2c2fcc9c292dafc01629d47042763a583a8c0b0518bb8c3944465a6ffab/substrates/manylinux_container/target-caches/pack_release_tcp_thread_closed_sdk/134b3060fc2aa095473846a39de8933308054baece1ffec1e6a502867dad0368
target="${FLUXON_BABY_MANYLINUX_TARGET:-/mnt/nvme0/mjq_build/fluxon_current_manylinux_target}"
release="${FLUXON_BABY_RELEASE_DIR:-/media/infra44/宝宝盘2/mjq_build/fluxon_current_release_20260717}"

mkdir -p "$target" "$release"

# Keep the high-churn Cargo target on local NVMe. Seed it with dereferenced
# runtime links so an explicit exFAT target override remains supported, then
# let Cargo rebuild every changed crate there. The finalized release still
# lands on 宝宝盘.
if [ ! -f "$target/.seed_complete" ]; then
  rsync -rltL \
    --no-perms \
    --no-owner \
    --no-group \
    "$seed/.rustc_info.json" \
    "$seed/cxxpacked" \
    "$seed/native_runtime" \
    "$seed/release" \
    "$seed/vendor_runtime" \
    "$target/"
  touch "$target/.seed_complete"
fi

# pub_prepare_build always verifies its host tools before honoring the native
# runtime skip. Seed those trees too so it never extracts uid/gid-bearing
# archives directly onto exFAT.
if [ ! -f "$target/.tool_seed_complete" ]; then
  rsync -rltL \
    --no-perms \
    --no-owner \
    --no-group \
    "$seed/dagviz" \
    "$seed/downloads" \
    "$seed/maturin" \
    "$seed/meson-0.64.0" \
    "$seed/target_cache_manifest.json" \
    "$target/"
  touch "$target/.tool_seed_complete"
fi

export FLUXON_CARGO_TARGET_CACHE="$target"
export FLUXON_RELEASE_DIR="$release"
export FLUXON_RELEASE_BASE="$base"
export FLUXON_BUILD_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_LINK_IMMUTABLE_ASSETS=0
export CARGO_BUILD_JOBS=1

bash "$helpers/build_e16ay_release.sh"
bash "$helpers/finalize_e16ay_release.sh"

# The worktree is intentionally uncommitted; preserve exact source evidence.
git -C "$repo" rev-parse HEAD > "$release/source_git_commit.txt"
git -C "$repo" status --short > "$release/source_git_status.txt"
(
  cd "$repo"
  # `git ls-files` includes mode-160000 gitlinks.  A checked-out submodule is
  # a directory, so feeding every tracked path directly to sha256sum aborts
  # the otherwise-valid release finalization.  Hash regular tracked content
  # here and preserve gitlinks separately from the exact index entry below.
  git ls-files -s -z \
    | LC_ALL=C sort -z \
    | while IFS= read -r -d '' entry; do
        meta="${entry%%$'\t'*}"
        path="${entry#*$'\t'}"
        mode="${meta%% *}"
        if [ "$mode" = 160000 ]; then
          continue
        fi
        sha256sum -- "$path"
      done
) > "$release/source_tracked_files.sha256"
git -C "$repo" ls-files -s \
  | awk '$1 == "160000" { print }' \
  > "$release/source_gitlinks.txt"
git -C "$repo" diff --binary -- . | sha256sum > "$release/source_worktree_diff.sha256"
(
  cd "$release"
  sha256sum \
    source_git_commit.txt \
    source_git_status.txt \
    source_gitlinks.txt \
    source_tracked_files.sha256 \
    source_worktree_diff.sha256 \
    >> fluxon_release.sha256
  sha256sum -c fluxon_release.sha256
)

find "$release" -maxdepth 1 -type f -name '*.whl' -exec sha256sum {} +
