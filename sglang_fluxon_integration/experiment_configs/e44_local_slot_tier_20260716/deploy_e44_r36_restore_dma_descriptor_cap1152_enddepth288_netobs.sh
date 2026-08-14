#!/usr/bin/env bash
set -euo pipefail

experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
r35_radix_source="$experiment/artifacts/e44_r35_loadback_lifecycle_observe_enddepth288_netobs_passed_20260720/config/unified_radix_cache_e44_r4.py"
host=116.238.240.2
variant=tier1_independent_005_netobs_enddepth288_dma_descriptor_cap1152
r34_release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r34_replica_operation_identity_20260720
r34_radix_sha256=72d3c7be4b71a90e5b04b944b387f9d549f3baa3a68cd4cd00703a2cd488dbee
r35_radix_sha256=895951ad37f5f4124b046854380c72ce77118cc2fd6eea8c6fae58b6b2c70c27
r36_radix_sha256=c53cd68b75f05476d57290c65143b2bb34625c7ee78962e0056b900b2c63572f
r34_pyo3_sha256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
host_patch_sha256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; mkdir -p '$remote_experiment/r36_baseline'"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/master_config_e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs.yaml" \
    "$experiment/fluxon_wait_ready.sh" \
    "$experiment/start_control_e44_v5_perf.sh" \
    "$experiment/launch_master_e44_v5_perf.sh" \
    "$experiment/launch_gpu_e44_r28_netobs.sh" \
    "$experiment/launch_cpu_e44_r28_netobs.sh" \
    "$experiment/launch_router_e44_v5_perf.sh" \
    "$experiment/run_workload_e44_r28_netobs.sh" \
    "$experiment/cluster_e44_r11.env" \
    "$experiment/hca_observer_e44_r28.py" \
    "$experiment/manage_hca_observer_e44_r28.sh" \
    "$experiment/analyze_hca_observer_e44_r28.py" \
    "$experiment/prepare_greptime_e44_r28.py" \
    "$experiment/import_hca_observer_to_greptime_e44_r28.py" \
    "$experiment/validate_e44_r35_loadback_observe.py" \
    "$experiment/validate_e44_r36_dma_descriptor_chunk.py" \
    "$experiment/benchmark_e44_r36_dma_descriptor_cap.py" \
    "root@$host:$remote_experiment/"

  if [ "$role" = gpu ]; then
    scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
      "$experiment/unified_radix_cache_e44_r4.py" \
      "root@$host:$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py"
    scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
      "$r35_radix_source" \
      "root@$host:$remote_experiment/r36_baseline/unified_radix_cache_e44_r35.py"
  fi

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; \
     if pgrep -af '[s]glang.launch_server' >/dev/null; then \
       echo 'refusing to deploy r36 over a live SGLang process' >&2; exit 1; \
     fi; \
     test \"\$(readlink -f '$root/fluxon_release')\" = '$r34_release'; \
     source '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$variant'; \
     test \"\$E44_PERF_RUN_ID\" = e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs; \
     test \"\$E44_PERF_HICACHE_BATCH_CONCURRENCY\" = 32; \
     test \"\$E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL\" = 1152; \
     test \"\$E44_PERF_EXPECTED_PYO3_SHA256\" = '$r34_pyo3_sha256'; \
     test \"\$E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256\" = '$r36_radix_sha256'; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F '\"policy\":\"prefix_end_depth_ratio\"' >/dev/null; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F '\"max_replica_pages_per_batch\":288' >/dev/null; \
     python3 -c \"compile(open('$remote_experiment/benchmark_e44_r36_dma_descriptor_cap.py', encoding='utf-8').read(), 'benchmark_e44_r36_dma_descriptor_cap.py', 'exec')\"; \
     bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' \
       '$remote_experiment/fluxon_wait_ready.sh' \
       '$remote_experiment/start_control_e44_v5_perf.sh' \
       '$remote_experiment/launch_master_e44_v5_perf.sh' \
       '$remote_experiment/launch_gpu_e44_r28_netobs.sh' \
       '$remote_experiment/launch_cpu_e44_r28_netobs.sh' \
       '$remote_experiment/launch_router_e44_v5_perf.sh' \
       '$remote_experiment/run_workload_e44_r28_netobs.sh' \
       '$remote_experiment/manage_hca_observer_e44_r28.sh'"

  if [ "$role" = gpu ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "set -e; \
       source '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$variant'; \
       site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages; \
       current=\$(sha256sum \"\$site/sglang/srt/mem_cache/unified_radix_cache.py\" | awk '{print \$1}'); \
       test \"\$current\" = '$r34_radix_sha256' -o \"\$current\" = '$r35_radix_sha256' -o \"\$current\" = '$r36_radix_sha256'; \
       test \"\$(sha256sum '$remote_experiment/r36_baseline/unified_radix_cache_e44_r35.py' | awk '{print \$1}')\" = '$r35_radix_sha256'; \
       test \"\$(sha256sum '$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py' | awk '{print \$1}')\" = '$r36_radix_sha256'; \
       grep -F 'SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL' '$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py' >/dev/null; \
       grep -F 'descriptors_per_layer=%d dma_calls=%d' '$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py' >/dev/null; \
       python3 '$remote_experiment/validate_e44_r35_loadback_observe.py' \
         '$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py'; \
       python3 '$remote_experiment/validate_e44_r36_dma_descriptor_chunk.py' \
         '$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py'; \
       \"\$E44_PERF_VENV_GPU/bin/python\" -c \"compile(open('$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py', encoding='utf-8').read(), 'unified_radix_cache_e44_r36_dma_cap.py', 'exec')\"; \
       install -m 0644 '$remote_experiment/unified_radix_cache_e44_r36_dma_cap.py' \
         \"\$site/sglang/srt/mem_cache/unified_radix_cache.py\"; \
       test \"\$(sha256sum \"\$site/sglang/srt/mem_cache/unified_radix_cache.py\" | awk '{print \$1}')\" = '$r36_radix_sha256'; \
       test \"\$(sha256sum \"\$site/sglang/srt/mem_cache/memory_pool_host.py\" | awk '{print \$1}')\" = '$host_patch_sha256'; \
       test \"\$(sha256sum \"\$E44_PERF_VENV_GPU/lib/python3.10/site-packages/fluxon_pyo3/fluxon_pyo3.abi3.so\" | awk '{print \$1}')\" = '$r34_pyo3_sha256'"
  fi
}

deploy_node 31408 fluxon_f1 gpu
deploy_node 30245 fluxon_f2 gpu
deploy_node 30729 fluxon_cpu cpu
