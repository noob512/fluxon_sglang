#!/usr/bin/env bash
set -euo pipefail

remote_release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r17_single_kv_pop_metadata_20260718
experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
host=116.238.240.2
expected_wheel_sha256=39df79dadb5199689f84d06f09aceefb42b4c77dbfea40b30ef879947497e6db

deploy_node() {
  local port="$1"
  local root_name="$2"
  local remote_experiment="/storage/mjq/sglang_fluxon/$root_name/e44_local_slot_tier_20260716"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "mkdir -p '$remote_experiment'; test \"\$(sha256sum '$remote_release/fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl' | awk '{print \$1}')\" = '$expected_wheel_sha256'"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/install_release_e44_r17_single_kv_pop.sh" \
    "$experiment/master_config_e44_r17_single_kv_pop_metadata_baseline.yaml" \
    "root@$host:$remote_experiment/"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "test \"\$(sha256sum '$remote_release/fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl' | awk '{print \$1}')\" = '$expected_wheel_sha256'; bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$remote_experiment/install_release_e44_r17_single_kv_pop.sh'"
}

deploy_node 31408 fluxon_f1
deploy_node 30245 fluxon_f2
deploy_node 30729 fluxon_cpu
