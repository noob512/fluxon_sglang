#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
variant_file="$script_dir/e44_v5_perf_variant_20260718.sh"
guard_file="$script_dir/launch_gpu_e44_r38_guarded.sh"
master_config=master_config_e44_r112_eager_all_post_read_netobs.yaml.in

grep -F 'tier1_independent_005_netobs_r112_eager_all_post_read_retain' "$variant_file" >/dev/null
grep -F 'tier1_independent_005_netobs_r112_eager_all_post_read_drop' "$variant_file" >/dev/null
grep -F '"policy":"eager_all"' "$variant_file" >/dev/null
grep -F 'tier1_independent_005_netobs_r112_eager_all_post_read_retain' "$guard_file" >/dev/null
grep -F 'tier1_independent_005_netobs_r112_eager_all_post_read_drop' "$guard_file" >/dev/null
grep -F '__E44_RUN_ID__' "$script_dir/$master_config" >/dev/null
grep -F 'eager-all variant unexpectedly retained bounded prefix admission' \
  "$script_dir/deploy_e44_two_stage_node_install.sh" >/dev/null

export E44_DEPLOY_VARIANT=tier1_independent_005_netobs_r112_eager_all_post_read_retain
export E44_DEPLOY_MASTER_CONFIG="$master_config"
exec bash "$script_dir/deploy_e44_r112_post_read_enddepth288_netobs.sh" "$@"
