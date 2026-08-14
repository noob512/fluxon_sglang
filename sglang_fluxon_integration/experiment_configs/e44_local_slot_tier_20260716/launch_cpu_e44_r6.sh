#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_cpu}"
export FLUXON_NODE0_IP=10.233.114.129 FLUXON_NODE1_IP=10.233.111.134 FLUXON_CPU_NODE_IP=10.233.125.121
export FLUXON_CPU_PYTHON_BIN="$root/venv-fluxon-e44-r6-20260716/bin/python"
export FLUXON_CPU_SITE_PACKAGES="$root/venv-fluxon-e44-r6-20260716/lib/python3.12/site-packages"
export FLUXON_CPU_EXPECTED_COMMU_CORE_SHA256=bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503
export FLUXON_CPU_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
export FLUXON_CPU_USER_RPC_SYNC_HANDLER_THREAD_COUNT=8
exec bash "$root/experiment_e16bb_rdma_numa1_20260714/launch_cpu_e16bb.sh" "$root" e44_r6
