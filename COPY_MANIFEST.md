# Fluxon + SGLang snapshot

Snapshot date: 2026-08-17 (Asia/Hong_Kong)

## Sources

| Component | Read-only source | Branch | HEAD |
| --- | --- | --- | --- |
| Fluxon | `/mnt/ceph/mjq/push_sglang/Fluxon` | `sglang-fluxon-kv-integration` | `20460ce6707c1199dca952f1b8c920c3dc5a46ae` |
| SGLang | `/mnt/ceph/mjq/push_sglang/sglang` | `main` | `a39ff98005e836014a34b499633a164fe0e1c2c6` |

The current source working trees were copied, so files newer than the recorded
HEAD commits are included. Source Git metadata was not copied or modified.

## Layout

- Fluxon source and documentation are at the repository root.
- The matching SGLang snapshot is under `sglang/`.
- Fluxon's SGLang integration design is under
  `fluxon_doc_cn/design/sglang_fluxon_kv集成设计.md`.

Historical release snapshots, duplicate SGLang trees, Git metadata, build
outputs, caches, generated local configuration, logs, and packaged release
artifacts were intentionally excluded. The canonical `fluxon_release/` source
support files remain, without generated archives, wheels, profiles, or bundled
external images.

## Integration boundary

This snapshot preserves the integration state present in the two source trees.
Fluxon contains the SGLang-oriented KV APIs and design, while the SGLang source
contains the matching atomic-group and radix-cache changes. The supplied SGLang
tree does not contain a dedicated `fluxon` storage backend, so this snapshot
does not claim a standalone deployable hostless adapter beyond the source state.
