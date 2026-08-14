#!/usr/bin/env bash
set -euo pipefail

root="${1:?missing Fluxon root}"
node="${2:?missing node0 or node1}"
expected_pyo3_sha256="${3:?missing expected PyO3 SHA256}"
case "$node" in
  node0|node1) ;;
  *) echo "unsupported node: $node" >&2; exit 2 ;;
esac

export ROOT_DIR="$root"
export FLUXON_NODE0_IP=10.233.114.139 FLUXON_NODE1_IP=10.233.114.138 FLUXON_NODE2_IP=10.233.125.121
export FLUXON_EXTERNAL_VENV_DIR=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r42-gpu-direct-staging-20260721
export FLUXON_EXTERNAL_OWNER_DRAM_BYTES=1073741824
export FLUXON_EXTERNAL_REPLICA_WRITEBACK_HOT_CAPACITY_RATIO=0.90
export FLUXON_EXTERNAL_RDMA_DEVICE_0=mlx5_4 FLUXON_EXTERNAL_RDMA_DEVICE_1=mlx5_6
export FLUXON_EXTERNAL_CLEAN_START=1
export FLUXON_EXTERNAL_OWNER_SESSION="e44_r42_gpu_get_smoke_owner_${node}"
export SGLANG_EXTERNAL_SESSION="e44_r42_gpu_get_smoke_unused_sglang_${node}"
export FLUXON_EXTERNAL_OWNER_ONLY=1
export FLUXON_EXTERNAL_DISABLE_OBSERVABILITY=false
export FLUXON_EXTERNAL_ICEORYX_EXTERNAL_BUSY_POLL=true
export FLUXON_EXTERNAL_ICEORYX_OWNER_CLIENT_BUSY_POLL=true
export FLUXON_EXTERNAL_EXPECTED_PYO3_SHA256="$expected_pyo3_sha256"
export FLUXON_EXTERNAL_EXPECTED_COMMU_CORE_SHA256=bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503
export FLUXON_EXTERNAL_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
export FLUXON_EXTERNAL_USER_RPC_SYNC_HANDLER_THREAD_COUNT=8
export RUST_LOG=info

exec bash "$root/experiment_e16bb_rdma_numa1_20260714/start_gpu_stack_owner_numa1.sh"
