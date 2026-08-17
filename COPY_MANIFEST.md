# Fluxon + SGLang latest experiment integration

Snapshot date: 2026-08-17 (Asia/Hong_Kong)

## Read-only sources

| Component | Source | Recorded branch | Recorded HEAD |
| --- | --- | --- | --- |
| Fluxon | `/mnt/ceph/mjq/push_sglang/Fluxon` | `sglang-fluxon-kv-integration` | `20460ce6707c1199dca952f1b8c920c3dc5a46ae` |
| SGLang | `/mnt/ceph/mjq/push_sglang/sglang` | `main` | `a39ff98005e836014a34b499633a164fe0e1c2c6` |

The source working trees, including files newer than the recorded commits, were
copied read-only. Source Git metadata was neither copied nor modified. Fluxon is
at the repository root; the runnable SGLang integration worktree is under
`sglang/`.

## Latest recoverable experiment identity

The newest recoverable experiment composition is FAST'25 E44 r134 from
2026-08-07. Its recorded identities are:

| Artifact | Recorded SHA256 |
| --- | --- |
| Unified radix r133 | `ad8475eb4c45228491c0094c3bbcbfcb2c84761a0d62d1dbb1b19c3ee318897a` |
| Fluxon HiCache adapter | `99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6` |
| Scheduler | `22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92` |
| Schedule batch | `8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a` |
| Metadata-only HostKV | `482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878` |
| Fluxon PyO3 runtime | `b4b6f8773b0b25967cd4920e6477f6d7b1534bd31d454b763c6fe43ed2787019` |

The validated policy was GDR off, prefetch threshold 64, batch concurrency 32,
batch-exists pin TTL 1200 ms, layer-batched background DMA enabled, eviction
write stream enabled, page-index validation disabled, and replica policy
`prefix_end_depth_ratio` with ratio 1.0, minimum 8 pages, and maximum 288 pages
per batch. The Fluxon master used post-read remote policy `drop` and eight TCP
control lanes.

## Integrated state

| Area | Target state |
| --- | --- |
| Commit 4 adapter | Added `storage/fluxon/hicache_fluxon.py`, package init, backend registration, server-argument choice, zero-copy v1 hook, and fake-store tests. |
| Adapter configuration | Strictly one `extra_config` field: `config_path`. Environment fallback, aliases, and tuning fields are rejected. |
| Unified radix | Recovered from the exact r133 artifact, then adapted to the current SGLang `MatchResult` API and the single fixed E44 policy. Current SHA256: `c8f701d5be36133a9b825b220e51861c3ba75c5e8fa8384422f612cb4c94ab58`. |
| Metadata-only HostKV | Merged into the current `memory_pool_host.py` and `pool_host/base.py`. It supports the E44 `MHATokenToKVPool` path and avoids materializing duplicate host KV payloads. |
| Scheduler | Current SGLang scheduler plus Fluxon enqueue/consume observations. Current SHA256: `0af87da3f9019f81ef9280259131612aa29170c40bc3139a17772a4dbe564895`. |
| Schedule batch | Current read-only SGLang version, SHA256 `df7bd231af59efeacbeddbad15cb50729b1cbc4c4ccb683669154df05f981ae7`. |
| SGL kernel | Added raw H2D plus MHA, MLA, and Mamba write/restore interfaces, Python wrappers, registration, and CUDA tests. The implementation uses asynchronous arbitrary-address copies on the active CUDA stream. |

The adapter and unified-radix files are intentionally not byte-identical to the
archived experiment files: current-SGLang API adaptation, configuration
contraction, warm-holder lifetime fixes, and backend-scoped CUDA initialization
change their hashes.

## Runtime contract

The SGLang-side configuration is:

```text
--enable-hierarchical-cache
--hicache-storage-backend fluxon
--hicache-write-policy write_back
--hicache-storage-backend-extra-config '{"config_path":"/absolute/path/to/fluxon.yaml"}'
```

No Fluxon-specific environment variable is required or accepted by the
adapter. The Fluxon YAML remains deployment-specific and must contain valid
cluster endpoints, paths, device topology, and the r134 post-read policy for the
target environment.

The current SGLang package declares Python >=3.10 and `torch==2.11.0`. The E44
r134 GPU environment recorded CUDA 12.8. Fluxon, its Python extension, SGLang,
and `sgl-kernel` must be rebuilt together in the target CUDA/RDMA environment.

## Validation completed here

- Byte-level Python compilation succeeded for 2,587 SGLang Python files.
- The five fake-store adapter tests passed with CPU `torch 2.11.0`.
- All seven Fluxon kernel interfaces have matching declarations,
  registrations, Python wrappers, and tests.
- `common_extension.cc` passed C++17 syntax checking against Torch 2.11 headers.
- The raw H2D operation registers both CPU descriptor dispatch and CUDA tensor
  dispatch; the real GDR-off path uses CPU descriptor tensors.

This host has no `nvcc` or GPU-enabled Torch installation, so the CUDA kernel
build, CUDA round-trip tests, RDMA deployment, and end-to-end E44 workload were
not executed here.

## Recovery limits and commit boundary

The exact r134 scheduler and schedule-batch files, the recorded PyO3 binary, and
the experiment's compiled CUDA operator binary were not preserved in the two
read-only sources. The scheduler hooks and CUDA operators in this worktree are
current-source integrations, not byte-for-byte recovery of those missing
artifacts. Therefore this worktree is the latest source-level reconstruction,
but it must not be described as a bit-identical reproduction or as
performance-validated until the hardware tests pass.

The complete `sglang/` tree is retained only as an integration worktree. For
the eventual history, the SGLang adapter, hooks, HostKV changes, and kernel
changes should be maintained and committed on the SGLang side; do not submit a
full SGLang snapshot as a Fluxon commit.
