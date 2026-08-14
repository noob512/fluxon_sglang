#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
experiment="$workspace/experiment_configs/e44_local_slot_tier_20260716"
host="${E44_DEPLOY_HOST:-116.238.240.2}"
identity="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
variant=tier1_independent_005_netobs_enddepth288_gpu_direct_r49_observe
runtime_sha256=a7598aca51f52d13e9c1d7709f0f08dce3b112b7b5e3748a4840d4fc9d8c18b2
adapter_sha256=7678033f95bff2f9ff9dfafa8994b2aa225cae655726b3004259cdd25b1a7961
validator_sha256=0edfeb528616a4cab328cdeffbe32b264e470e65f7d06e7b3d04c9a6c8e03eb4
ssh_common=(-o BatchMode=yes -o StrictHostKeyChecking=no -i "$identity" -o IdentitiesOnly=yes)
scp_common=(-q -o BatchMode=yes -o StrictHostKeyChecking=no -i "$identity" -o IdentitiesOnly=yes)

test -f "$identity"
test "$(sha256sum "$experiment/unified_radix_cache_e44_r42_gpu_direct_staging.py" | awk '{print $1}')" = "$runtime_sha256"
test "$(sha256sum "$experiment/hicache_fluxon_e44_r42_gpu_direct_staging.py" | awk '{print $1}')" = "$adapter_sha256"
test "$(sha256sum "$experiment/validate_e44_r42_gpu_direct_staging.py" | awk '{print $1}')" = "$validator_sha256"

files=(
  e44_v5_perf_variant_20260718.sh
  master_config_e44_r49_gpu_direct_admission_observe_enddepth288_netobs.yaml
  unified_radix_cache_e44_r42_gpu_direct_staging.py
  hicache_fluxon_e44_r42_gpu_direct_staging.py
  validate_e44_r42_gpu_direct_staging.py
  launch_gpu_e44_r38_guarded.sh
)

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"

  ssh "${ssh_common[@]}" -p "$port" "root@$host" \
    "set -e; \
     test -z \"\$(pgrep -af '[f]luxon_py.runtime.start_master|[f]luxon_py.runtime.start_owner_kvclient|[s]glang.launch_server' || true)\"; \
     mkdir -p '$remote_experiment'"
  scp "${scp_common[@]}" -P "$port" \
    "${files[@]/#/$experiment/}" "root@$host:$remote_experiment/"
  ssh "${ssh_common[@]}" -p "$port" "root@$host" \
    "set -e; \
     source '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$variant'; \
     test \"\$E44_PERF_HICACHE_BATCH_CONCURRENCY\" = 32; \
     test \"\$E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL\" = 0; \
     test \"\$E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256\" = '$runtime_sha256'; \
     test \"\$E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256\" = '$adapter_sha256'; \
     if [ '$role' = gpu ]; then \
       test -x \"\$E44_PERF_VENV_GPU/bin/python\"; \
     else \
       test -x \"\$E44_PERF_VENV_CPU/bin/python\"; \
     fi; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F 'prefix_end_depth_ratio' >/dev/null; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F 'max_replica_pages_per_batch\":288' >/dev/null; \
     test \"\$(sha256sum '$remote_experiment/validate_e44_r42_gpu_direct_staging.py' | awk '{print \$1}')\" = '$validator_sha256'; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/validate_e44_r42_gpu_direct_staging.py' \
       '$remote_experiment/unified_radix_cache_e44_r42_gpu_direct_staging.py' \
       '$remote_experiment/hicache_fluxon_e44_r42_gpu_direct_staging.py' >/dev/null"

  if [ "$role" = gpu ]; then
    ssh "${ssh_common[@]}" -p "$port" "root@$host" \
      "set -e; \
       site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache; \
       install -m 0644 '$remote_experiment/unified_radix_cache_e44_r42_gpu_direct_staging.py' \"\$site/unified_radix_cache.py\"; \
       install -m 0644 '$remote_experiment/hicache_fluxon_e44_r42_gpu_direct_staging.py' \"\$site/storage/fluxon/hicache_fluxon.py\"; \
       test \"\$(sha256sum \"\$site/unified_radix_cache.py\" | awk '{print \$1}')\" = '$runtime_sha256'; \
       test \"\$(sha256sum \"\$site/storage/fluxon/hicache_fluxon.py\" | awk '{print \$1}')\" = '$adapter_sha256'"
  fi
}

case "${1:-all}" in
  all)
    deploy_node 32656 fluxon_f1 gpu
    deploy_node 30245 fluxon_f2 gpu
    deploy_node 30729 fluxon_cpu cpu
    ;;
  node0) deploy_node 32656 fluxon_f1 gpu ;;
  node1) deploy_node 30245 fluxon_f2 gpu ;;
  cpu) deploy_node 30729 fluxon_cpu cpu ;;
  *) echo "usage: $0 [all|node0|node1|cpu]" >&2; exit 2 ;;
esac

printf 'runtime_sha256=%s\nadapter_sha256=%s\nvalidator_sha256=%s\n' \
  "$runtime_sha256" "$adapter_sha256" "$validator_sha256"
