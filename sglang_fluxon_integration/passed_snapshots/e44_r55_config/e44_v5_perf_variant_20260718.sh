#!/usr/bin/env bash

e44_perf_variant="${1:?missing E44 performance variant}"
E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-v5perf-20260718
E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-v5perf-20260718
E44_PERF_EXPECTED_PYO3_SHA256=ea42a5966b59b879645c23b58335f5acf501d43a20639bb23492250e786015ec
E44_PERF_EXPECTED_COMMU_CORE_SHA256=bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503
E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU="$E44_PERF_EXPECTED_COMMU_CORE_SHA256"
E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU="$E44_PERF_EXPECTED_RDMA_PROBE_SHA256"
E44_PERF_EXPECTED_MEMORY_POOL_HOST_SHA256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878
E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=72d3c7be4b71a90e5b04b944b387f9d549f3baa3a68cd4cd00703a2cd488dbee
E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=776d990f879dae2a9c543275fe3fefb623e11a73ea51792edafc7e5fd58d0e9e
E44_PERF_EXPECTED_SCHEDULER_SHA256=
E44_PERF_HICACHE_BATCH_CONCURRENCY=32
E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
case "$e44_perf_variant" in
  baseline)
    E44_PERF_RUN_ID=e44_r12_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r12_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    ;;
  pinaware_baseline)
    E44_PERF_RUN_ID=e44_r16_pinaware_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r16_pinaware_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r16-pinaware-20260718
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r16-pinaware-20260718
    E44_PERF_EXPECTED_PYO3_SHA256=0628fa575180e22c99d75957c142584e2269138c4775cfa3dfb703d57f9c8fdf
    ;;
  single_kv_baseline)
    E44_PERF_RUN_ID=e44_r17_single_kv_pop_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r17_single_kv_pop_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r17-single-kv-pop-20260718
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r17-single-kv-pop-20260718
    E44_PERF_EXPECTED_PYO3_SHA256=c62e58344e592f0cb2043545a3936faed3ef3fc314992aa9d6a58ab54c4d3e2f
    ;;
  direct_delete_singleflight_baseline)
    E44_PERF_RUN_ID=e44_r18_direct_delete_singleflight_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r18_direct_delete_singleflight_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=7e307f646296d37634cc3339cc0dd156c0667e4f9c2d7c66c594da50f05780c6
    ;;
  direct_delete_singleflight_tier1_075)
    E44_PERF_RUN_ID=e44_r19_direct_delete_singleflight_tier1_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r19_direct_delete_singleflight_tier1_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=7e307f646296d37634cc3339cc0dd156c0667e4f9c2d7c66c594da50f05780c6
    ;;
  owner_remote_put_singleflight_tier1_075)
    E44_PERF_RUN_ID=e44_r20_owner_remote_put_singleflight_tier1_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r20_owner_remote_put_singleflight_tier1_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r20-owner-remote-put-singleflight-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r20-owner-remote-put-singleflight-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=98442cc4312cee2bc3b48715eccb6aa0545b99778997f98f4de4a3fec23746eb
    ;;
  tier1_independent_075)
    E44_PERF_RUN_ID=e44_r21_tier1_independent_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r21_tier1_independent_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_005)
    E44_PERF_RUN_ID=e44_r22_tier1_independent_005
    E44_PERF_MASTER_CONFIG=master_config_e44_r22_tier1_independent_005.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_005_netobs_replay)
    # Network-observability replay of r22. Cache policy, release, workload, and
    # concurrency stay byte-for-byte aligned with tier1_independent_005.
    E44_PERF_RUN_ID=e44_r28_r22_netobs_replay
    E44_PERF_MASTER_CONFIG=master_config_e44_r28_r22_netobs_replay.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_005_netobs_ack_batch)
    # Single-variable replay of r28: only External holder release ACKs change
    # from one RPC per holder to generation-safe batches.
    E44_PERF_RUN_ID=e44_r30_external_ack_batch_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r30_external_ack_batch_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=e3a6e6f89455b759b9654bd25c822a6837f1e34aae646a9a1e5212575afe778b
    ;;
  tier1_independent_005_netobs_ack_batch_retry)
    # Isolated retry of r30 attempt1. All behavior knobs and the release stay
    # identical; only run-scoped identifiers and output paths change.
    E44_PERF_RUN_ID=e44_r30b_external_ack_batch_netobs_retry
    E44_PERF_MASTER_CONFIG=master_config_e44_r30b_external_ack_batch_netobs_retry.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=e3a6e6f89455b759b9654bd25c822a6837f1e34aae646a9a1e5212575afe778b
    ;;
  tier1_independent_005_netobs_ack_batch_source_fence_wait)
    # r31 correctness replay of r30b. The only release behavior change is
    # waiting for the exact source-selection/reclaim generation before an
    # idempotent local-first Put re-evaluates its complete atomic_batch.
    E44_PERF_RUN_ID=e44_r31_source_fence_wait_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r31_source_fence_wait_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109
    ;;
  tier1_independent_005_netobs_ack_batch_source_fence_wait_enddepth288)
    # r32 single-variable replay of r31. Keep the validated r31 release,
    # Get32, tier1 5%, capacities, workload, and observability unchanged;
    # only switch replica admission from start-depth/160 to end-depth/288.
    E44_PERF_RUN_ID=e44_r32_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r32_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109
    ;;
  tier1_independent_005_netobs_enddepth288_busy_activity_observe)
    # r33 attribution replay of r32. All performance knobs stay identical;
    # only the release adds structured Busy/activity and owner-wait logs.
    E44_PERF_RUN_ID=e44_r33_busy_activity_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r33_busy_activity_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r33-busy-activity-observe-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r33-busy-activity-observe-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d998fb2a7699a8b44d21b059785c16175359ea5ea120a71352fa6bb80224b5de
    ;;
  tier1_independent_005_netobs_enddepth288_replica_operation_identity)
    # r34 correctness replay of r33. All performance knobs and observation
    # stay identical; only replica append completion becomes operation-scoped.
    E44_PERF_RUN_ID=e44_r34_replica_operation_identity_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r34_replica_operation_identity_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
    ;;
  tier1_independent_005_netobs_enddepth288_loadback_observe)
    # r35 is observation-only on top of r34. Fluxon binaries and every
    # performance knob remain unchanged; only the deployed SGLang radix
    # source adds request-lifecycle and synchronous-eviction breakdowns.
    E44_PERF_RUN_ID=e44_r35_loadback_lifecycle_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r35_loadback_lifecycle_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=895951ad37f5f4124b046854380c72ce77118cc2fd6eea8c6fae58b6b2c70c27
    ;;
  tier1_independent_005_netobs_enddepth288_dma_descriptor_cap1152)
    # r36 changes only the maximum raw descriptor count in one H2D batch API
    # call. Logical restore batches, streams, events, operations, and all
    # Fluxon/cache policy settings remain identical to r35.
    E44_PERF_RUN_ID=e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=c53cd68b75f05476d57290c65143b2bb34625c7ee78962e0056b900b2c63572f
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=1152
    ;;
  tier1_independent_005_netobs_enddepth288_get_prefix_reuse)
    # r38 derives SGLang from sealed r35 and changes only TP common-prefix
    # handle consumption. Fluxon adds consume_prefix_len and releases the
    # unconsumed tail; cache policy and all performance knobs stay fixed.
    E44_PERF_RUN_ID=e44_r38_get_prefix_reuse_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r38_get_prefix_reuse_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r38-get-prefix-reuse-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r38-get-prefix-reuse-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=3e5b9d41af89357d57f09664a4029ef5c12b189b32d53cc8f58fd19c14537ac2
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=8d1b497fd35ef563e792f6195ca502b67b17e4afd2cfc79f8db0b1846236a5da
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=b2d34b0fa045a24f632f626bfdf8dc776045d90c791023765e9557ab03afb27e
    ;;
  tier1_independent_005_netobs_enddepth288_get_ready_observe)
    # r39 is observation-only relative to r38. Workload, cache policy,
    # transfer concurrency, DMA behavior, and SGLang code stay identical.
    E44_PERF_RUN_ID=e44_r39_get_ready_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r39_get_ready_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r39-get-ready-observe-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r39-get-ready-observe-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=759333b357783b7983a4bd17bb7ea30f0828ca0d36be5afb92a5bf5c4329421f
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=8d1b497fd35ef563e792f6195ca502b67b17e4afd2cfc79f8db0b1846236a5da
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=b2d34b0fa045a24f632f626bfdf8dc776045d90c791023765e9557ab03afb27e
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r47)
    # Full r47 validation keeps the sealed r39 workload, cache policy,
    # capacities, Get32, DMA0, and admission unchanged.  The only behavior
    # change is r47 Fluxon plus the validated r42 caller-owned GPU staging.
    E44_PERF_RUN_ID=e44_r47_gpu_direct_full_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r47_gpu_direct_full_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r47-gpu-direct-full-enddepth288-netobs-20260721
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r47-gpu-direct-full-cpu-host-20260721
    E44_PERF_EXPECTED_PYO3_SHA256=ef48cf9852440a6bb33eefc9d036cf6cec3f2f5f7386d09230c0abcdbf35b162
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=55eb59eb07827010016d320eea0d7615834ea3c21d70148cc15951c081f13d09
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=2139404e489268fe5803d19f7be585020359a8351d4b1683733e4cb5ace9deb6
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=574c23041a4c185e52b5f67c98a4486138bf869639842786d2d3cf1453c5520c
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r48)
    # Exact replay of the r47 full-load configuration.  The only runtime
    # change is the closed PPLX single-worker mapping that lets TP1 register
    # a caller-owned CUDA device-1 staging buffer against worker 0.
    E44_PERF_RUN_ID=e44_r48_gpu_direct_single_worker_gpu1_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r48_gpu_direct_single_worker_gpu1_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r48-gpu-direct-single-worker-gpu1-20260722
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r48-gpu-direct-full-cpu-host-20260722
    E44_PERF_EXPECTED_PYO3_SHA256=36f8336198e1eee239bf8fbf3811dbf784c6a788cfc55b24d2614eedd0e129eb
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=075461f1af1bf710061b4bd2ab18f7f3ceee7b9bfee8a16d16ab61e0c67e19e3
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=574c23041a4c185e52b5f67c98a4486138bf869639842786d2d3cf1453c5520c
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r49_observe)
    # Observation-only replay of r48. Fluxon binaries, 288-slot staging,
    # workload, capacities, cache policy, Get32, and DMA0 stay unchanged;
    # only the two deployed SGLang sources classify GPU staging admission
    # and report lease lifetime/pool occupancy.
    E44_PERF_RUN_ID=e44_r49_gpu_direct_admission_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r49_gpu_direct_admission_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r48-gpu-direct-single-worker-gpu1-20260722
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r48-gpu-direct-full-cpu-host-20260722
    E44_PERF_EXPECTED_PYO3_SHA256=36f8336198e1eee239bf8fbf3811dbf784c6a788cfc55b24d2614eedd0e129eb
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=a7598aca51f52d13e9c1d7709f0f08dce3b112b7b5e3748a4840d4fc9d8c18b2
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=7678033f95bff2f9ff9dfafa8994b2aa225cae655726b3004259cdd25b1a7961
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r50_plan_bind)
    # Exact r49 workload/config replay. The only functional variable is the
    # generation-safe Get plan, exact GPU reserve, and same-plan CPU fallback.
    E44_PERF_RUN_ID=e44_r50_plan_bind_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r50_plan_bind_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r50-plan-bind-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r50-plan-bind-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=5094e229e286bfed079d4971d857bf96327ed2dfd460ff344a78a35fd860fbbd
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=3bdab2956a5a255423a7331c5c84dfec9f1be35b5de6b2bdd7169c8a7ed8aab7
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=1cc7153e846ffcd9f32e11f58e55fff2c5b7725b39123b78a93de9319b33114a
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r51_metadata_only_plan)
    # Exact r49/r50 workload and configuration replay.  Relative to r50,
    # Plan is metadata-only and installs activity only after Bind revalidation.
    E44_PERF_RUN_ID=e44_r51_metadata_only_plan_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r51_metadata_only_plan_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r51-metadata-only-plan-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r51-metadata-only-plan-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=0d1ee92db91ea58a31e78ce796f1d22a31a10e14ffafbb7a4e9d6715cdddba64
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=3bdab2956a5a255423a7331c5c84dfec9f1be35b5de6b2bdd7169c8a7ed8aab7
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=1cc7153e846ffcd9f32e11f58e55fff2c5b7725b39123b78a93de9319b33114a
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r52_owner_local_first)
    # Exact r51 workload/config replay. The only performance variable is that
    # owner-local holders are pinned before Plan and only remote positions
    # enter master metadata and CPU/GPU destination selection.
    E44_PERF_RUN_ID=e44_r52_owner_local_first_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r52_owner_local_first_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r52-owner-local-first-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r52-owner-local-first-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=a0cf3087e32335b6dc6e25d8f6bc546a70bbb864cd5f160453030cf94ff8ee33
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=49679742cc74e581f502c622a9483639ada0937c51afbb9b6b72cbd1a887e848
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=5da41b355bf6d1bbba98dde5b746073f14b8ea3bb2215140c365d60f5884edd9
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r53_rust_slab)
    # Exact r52 attempt2 workload/config replay. The only implementation
    # variable is moving the fixed GPU staging slot freelist from Python into
    # fluxon_util and exposing it through fluxon_pyo3.FixedSlabAllocator.
    E44_PERF_RUN_ID=e44_r53_rust_slab_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r53_rust_slab_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r53-rust-slab-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r53-rust-slab-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=e107038c791197bc50d02bdbbfc1fa9c5fdc6007af231ec5fdc98e8e726f0075
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=49679742cc74e581f502c622a9483639ada0937c51afbb9b6b72cbd1a887e848
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=d66e5ea4d4a61cc5d1abe81b637070a3d228dd69e6d51f9b071f6183cee9f955
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r54_prefetch_timeline)
    # Exact r53 workload/config replay. This is observation-only: request-level
    # plan/reserve/RDMA-terminal/scheduler-consume/restore/release timestamps
    # are joined without changing admission, queue order, or staging capacity.
    E44_PERF_RUN_ID=e44_r54_prefetch_timeline_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r54-prefetch-timeline-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r54-prefetch-timeline-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=2f3cf88322c937de744298716c55fef92ea30e85b18a664119872c72ee10645c
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=920cb610334668a5b0199d533d998c111d364de48328b16664010b885f9de554
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r55_planned_get_cancel_safe)
    # Exact r54 workload/config replay. Only the planned CPU Get cancellation
    # ownership and foreground timeout differ in Fluxon.
    E44_PERF_RUN_ID=e44_r55_planned_get_cancel_safe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=920cb610334668a5b0199d533d998c111d364de48328b16664010b885f9de554
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_get64)
    # Single-variable replay of r28: only Get payload transfer concurrency
    # changes from 32 to 64.
    E44_PERF_RUN_ID=e44_r29_get_batch64_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r29_get_batch64_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    E44_PERF_HICACHE_BATCH_CONCURRENCY=64
    ;;
  tier1_independent_010)
    E44_PERF_RUN_ID=e44_r23_tier1_independent_010
    E44_PERF_MASTER_CONFIG=master_config_e44_r23_tier1_independent_010.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_018)
    E44_PERF_RUN_ID=e44_r24_tier1_independent_018
    E44_PERF_MASTER_CONFIG=master_config_e44_r24_tier1_independent_018.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_025)
    E44_PERF_RUN_ID=e44_r25_tier1_independent_025
    E44_PERF_MASTER_CONFIG=master_config_e44_r25_tier1_independent_025.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_030)
    E44_PERF_RUN_ID=e44_r27_tier1_independent_030
    E44_PERF_MASTER_CONFIG=master_config_e44_r27_tier1_independent_030.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_050)
    E44_PERF_RUN_ID=e44_r26_tier1_independent_050
    E44_PERF_MASTER_CONFIG=master_config_e44_r26_tier1_independent_050.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_075)
    E44_PERF_RUN_ID=e44_r13_tier1_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r13_tier1_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    ;;
  enddepth288)
    E44_PERF_RUN_ID=e44_r14_enddepth288
    E44_PERF_MASTER_CONFIG=master_config_e44_r14_enddepth288.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    ;;
  r15_enddepth288_selected_credit)
    E44_PERF_RUN_ID=e44_r15_enddepth288_selected_credit
    E44_PERF_MASTER_CONFIG=master_config_e44_r15_enddepth288_selected_credit.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r15-selected-credit-20260718
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r15-selected-credit-20260718
    E44_PERF_EXPECTED_PYO3_SHA256=c79cdba41aa3556ec4e9a89743dc1030b8229ce964e283171ea2bde1b5380b37
    ;;
  *)
    echo "unsupported E44 performance variant: $e44_perf_variant" >&2
    return 2 2>/dev/null || exit 2
    ;;
esac
