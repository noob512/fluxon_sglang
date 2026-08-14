#!/usr/bin/env bash
set -euo pipefail

experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
host=116.238.240.2
variant=tier1_independent_005_netobs_ack_batch_source_fence_wait_enddepth288
expected_release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r31_source_fence_wait_20260719
expected_pyo3_sha256=17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109
expected_variant_sha256="$(sha256sum "$experiment/e44_v5_perf_variant_20260718.sh" | awk '{print $1}')"
expected_master_sha256="$(sha256sum "$experiment/master_config_e44_r32_enddepth288_netobs.yaml" | awk '{print $1}')"

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; mkdir -p '$remote_experiment'; test \"\$(readlink -f '$root/fluxon_release')\" = '$expected_release'"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/master_config_e44_r32_enddepth288_netobs.yaml" \
    "root@$host:$remote_experiment/"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; \
     bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh'; \
     source '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$variant'; \
     test \"\$E44_PERF_RUN_ID\" = e44_r32_enddepth288_netobs; \
     test \"\$E44_PERF_HICACHE_BATCH_CONCURRENCY\" = 32; \
     test \"\$E44_PERF_EXPECTED_PYO3_SHA256\" = '$expected_pyo3_sha256'; \
     test \"\$E44_PERF_MASTER_CONFIG\" = master_config_e44_r32_enddepth288_netobs.yaml; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F '\"policy\":\"prefix_end_depth_ratio\"' >/dev/null; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F '\"max_replica_pages_per_batch\":288' >/dev/null; \
     test \"\$(sha256sum '$remote_experiment/e44_v5_perf_variant_20260718.sh' | awk '{print \$1}')\" = '$expected_variant_sha256'; \
     test \"\$(sha256sum '$remote_experiment/master_config_e44_r32_enddepth288_netobs.yaml' | awk '{print \$1}')\" = '$expected_master_sha256'"

  if [ "$role" = gpu ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "test -x /storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r31-source-fence-wait-20260719/bin/python"
  else
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "test -x /storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r31-source-fence-wait-20260719/bin/python"
  fi
}

deploy_node 31408 fluxon_f1 gpu
deploy_node 30245 fluxon_f2 gpu
deploy_node 30729 fluxon_cpu cpu
