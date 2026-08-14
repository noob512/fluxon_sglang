#!/usr/bin/env bash
set -euo pipefail

experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
host=116.238.240.2
release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r18_direct_delete_singleflight_metadata_20260719
wheel="$release/fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl"
expected_wheel_sha256=cecd818b3c398156b15a6086ba3990ccfd459dad90c2880f0cb4e650983b0c68

deploy_node() {
  local port="$1"
  local root_name="$2"
  local remote_experiment="/storage/mjq/sglang_fluxon/$root_name/e44_local_slot_tier_20260716"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "mkdir -p '$remote_experiment'; test \"\$(readlink -f '/storage/mjq/sglang_fluxon/$root_name/fluxon_release')\" = '$release'; test \"\$(sha256sum '$wheel' | awk '{print \$1}')\" = '$expected_wheel_sha256'"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/master_config_e44_r19_direct_delete_singleflight_tier1_075.yaml" \
    "$experiment/fluxon_wait_ready.sh" \
    "$experiment/start_control_e44_v5_perf.sh" \
    "$experiment/launch_master_e44_v5_perf.sh" \
    "$experiment/launch_gpu_e44_v5_perf.sh" \
    "$experiment/launch_cpu_e44_v5_perf.sh" \
    "$experiment/launch_router_e44_v5_perf.sh" \
    "root@$host:$remote_experiment/"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$remote_experiment/fluxon_wait_ready.sh' '$remote_experiment/start_control_e44_v5_perf.sh' '$remote_experiment/launch_master_e44_v5_perf.sh' '$remote_experiment/launch_gpu_e44_v5_perf.sh' '$remote_experiment/launch_cpu_e44_v5_perf.sh' '$remote_experiment/launch_router_e44_v5_perf.sh'"
}

deploy_node 31408 fluxon_f1
deploy_node 30245 fluxon_f2
deploy_node 30729 fluxon_cpu
