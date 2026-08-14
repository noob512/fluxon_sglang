#![allow(unused_assignments)]

use crate::cluster_manager::NodeIDString;
use crate::master_kv_router::msg_pack::PutAtomicGroup;
use crate::p2p::msg_pack::{MsgPackSerializePart, RPCReq};
use crate::rpcresp_kvresult_convert::msg_and_error::{ErrorCode, MsgId};
use bitcode::{Decode, Encode};

/// Stable identity of one owner process generation.
#[derive(Default, Debug, Clone, PartialEq, Eq, Hash, Encode, Decode)]
pub struct OwnerGeneration {
    pub node_id: NodeIDString,
    pub node_start_time: i64,
}

impl OwnerGeneration {
    pub fn new(node_id: impl Into<NodeIDString>, node_start_time: i64) -> Self {
        Self {
            node_id: node_id.into(),
            node_start_time,
        }
    }

    pub fn is_initialized(&self) -> bool {
        !self.node_id.is_empty() && self.node_start_time != 0
    }

    #[cfg(test)]
    pub fn for_test(node_id: &str) -> Self {
        Self::new(node_id, 1)
    }
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Hash, Encode, Decode)]
pub enum OwnerSlotScope {
    #[default]
    LocalExclusive,
    GlobalShared,
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Hash, Encode, Decode)]
pub enum OwnerTargetDisposition {
    #[default]
    EphemeralCaller,
    LocalExclusive,
    GlobalShared,
    TransientSsdRead,
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Hash, Encode, Decode)]
pub enum OwnerTransferOpKind {
    #[default]
    Get,
    Put,
    ReplicaAppend,
    SsdLoad,
    Repair,
}

/// Generation-safe identity shared by source and target owner RPCs.
#[derive(Default, Debug, Clone, PartialEq, Eq, Hash, Encode, Decode)]
pub struct OwnerTransferOpId {
    pub coordinator: OwnerGeneration,
    pub sequence: u64,
    pub kind: OwnerTransferOpKind,
}

impl OwnerTransferOpId {
    pub fn new(
        coordinator: OwnerGeneration,
        sequence: u64,
        kind: OwnerTransferOpKind,
    ) -> Self {
        Self {
            coordinator,
            sequence,
            kind,
        }
    }

    pub fn is_initialized(&self) -> bool {
        self.coordinator.is_initialized() && self.sequence != 0
    }
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Hash, Encode, Decode)]
pub struct OwnerLeaseId {
    pub owner: OwnerGeneration,
    pub sequence: u64,
}

impl OwnerLeaseId {
    pub fn is_initialized(&self) -> bool {
        self.owner.is_initialized() && self.sequence != 0
    }
}

/// The only physical slot descriptor used by owner allocator, owner RPC and
/// master route metadata. `allocation_id` is never reused within one owner
/// generation; an offset alone is never a release capability.
#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub struct OwnerSlotDesc {
    pub owner: OwnerGeneration,
    pub allocation_id: u64,
    /// Byte offset inside the owner's complete registered segment.
    pub segment_offset: u64,
    /// 4 KiB-aligned physical allocation capacity.
    pub capacity_bytes: u64,
    pub addr: u64,
    pub base_addr: u64,
    pub len: u64,
    /// Generation of the segment registration used by the transfer backend.
    pub segment_registration_epoch: u64,
}

impl OwnerSlotDesc {
    pub fn end_addr(&self) -> Option<u64> {
        self.addr.checked_add(self.capacity_bytes)
    }

    pub fn geometry_matches(&self, other: &Self) -> bool {
        self.owner == other.owner
            && self.allocation_id == other.allocation_id
            && self.segment_offset == other.segment_offset
            && self.capacity_bytes == other.capacity_bytes
            && self.addr == other.addr
            && self.base_addr == other.base_addr
    }

    pub fn is_valid(&self) -> bool {
        self.owner.is_initialized()
            && self.allocation_id != 0
            && self.capacity_bytes != 0
            && self.len <= self.capacity_bytes
            && self.segment_registration_epoch != 0
            && self.addr == self.base_addr.checked_add(self.segment_offset).unwrap_or(u64::MAX)
    }
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Hash)]
pub struct OwnerManifestKey {
    pub key: String,
    pub put_id: (u64, u32),
}

impl OwnerManifestKey {
    pub fn new(key: impl Into<String>, put_id: (u64, u32)) -> Self {
        Self {
            key: key.into(),
            put_id,
        }
    }
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq)]
pub enum OwnerSlotPhysicalState {
    #[default]
    Reserved,
    DataReady,
    RoutePending,
    Committed,
    Reclaiming,
}

#[derive(Default, Debug, Clone, PartialEq, Eq)]
pub struct OwnerSlotManifestEntry {
    pub key: String,
    pub put_id: (u64, u32),
    pub slot: OwnerSlotDesc,
    pub scope: Option<OwnerSlotScope>,
    pub disposition: OwnerTargetDisposition,
    pub route_epoch: u64,
    pub physical_state: OwnerSlotPhysicalState,
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub struct OwnerSourceRouteToken {
    pub key: String,
    pub put_id: (u64, u32),
    pub route_epoch: u64,
    pub source: OwnerSlotDesc,
    pub atomic_batch: Option<PutAtomicGroup>,
    pub plan_nonce: u64,
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub struct OwnerTargetRouteToken {
    pub key: String,
    pub put_id: (u64, u32),
    pub operation: OwnerTransferOpId,
    pub target_owner: OwnerGeneration,
    pub prior_route_epoch: u64,
    pub policy_epoch: u64,
    pub atomic_batch: Option<PutAtomicGroup>,
    pub plan_nonce: u64,
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Encode, Decode)]
pub enum OwnerTransferDirection {
    #[default]
    RdmaRead,
    RdmaWrite,
    IpcCopy,
    LocalCopy,
    ZeroCopy,
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub struct OwnerTransferReceipt {
    pub completion_id: u64,
    pub direction: OwnerTransferDirection,
    pub bytes: u64,
    pub source: Option<OwnerSlotDesc>,
    pub target: OwnerSlotDesc,
    pub source_registration_epoch: u64,
    pub target_registration_epoch: u64,
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Encode, Decode)]
pub enum OwnerTransferOutcome {
    #[default]
    Success,
    Failed,
    Cancelled,
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Encode, Decode)]
pub enum OwnerTargetLeaseStateView {
    #[default]
    Prepared,
    DataReady,
    RoutePending,
    Committed,
    Aborted,
}

#[derive(Default, Debug, Clone, Copy, PartialEq, Eq, Encode, Decode)]
pub enum OwnerTransferErrorCode {
    #[default]
    InvalidArgument,
    StaleGeneration,
    NotFound,
    Conflict,
    Busy,
    NoSpace,
    Reclaiming,
    RouteCommitRequired,
    Internal,
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub struct OwnerTransferItemError {
    pub code: OwnerTransferErrorCode,
    pub detail: String,
}

impl OwnerTransferItemError {
    pub fn new(code: OwnerTransferErrorCode, detail: impl Into<String>) -> Self {
        Self {
            code,
            detail: detail.into(),
        }
    }
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub enum OwnerSegmentTransferItem {
    #[default]
    Invalid,
    AcquireSource {
        op_id: OwnerTransferOpId,
        route_token: OwnerSourceRouteToken,
    },
    PrepareTarget {
        op_id: OwnerTransferOpId,
        expected_target: OwnerGeneration,
        key: String,
        put_id: (u64, u32),
        len: u64,
        disposition: OwnerTargetDisposition,
        atomic_batch: Option<PutAtomicGroup>,
    },
    ReleaseSource {
        op_id: OwnerTransferOpId,
        lease_id: OwnerLeaseId,
        outcome: OwnerTransferOutcome,
    },
    CommitTarget {
        op_id: OwnerTransferOpId,
        lease_id: OwnerLeaseId,
        receipt: OwnerTransferReceipt,
        route_token: Option<OwnerTargetRouteToken>,
    },
    AbortTarget {
        op_id: OwnerTransferOpId,
        lease_id: OwnerLeaseId,
        reason: String,
    },
}

impl OwnerSegmentTransferItem {
    pub fn op_id(&self) -> Option<&OwnerTransferOpId> {
        match self {
            Self::Invalid => None,
            Self::AcquireSource { op_id, .. }
            | Self::PrepareTarget { op_id, .. }
            | Self::ReleaseSource { op_id, .. }
            | Self::CommitTarget { op_id, .. }
            | Self::AbortTarget { op_id, .. } => Some(op_id),
        }
    }
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub enum OwnerSegmentTransferOutcome {
    #[default]
    Invalid,
    SourceAcquired {
        lease_id: OwnerLeaseId,
        slot: OwnerSlotDesc,
    },
    SourceReleased,
    TargetPrepared {
        lease_id: OwnerLeaseId,
        slot: OwnerSlotDesc,
        state: OwnerTargetLeaseStateView,
    },
    TargetCommitPending {
        lease_id: OwnerLeaseId,
        slot: OwnerSlotDesc,
    },
    TargetCommitted {
        lease_id: OwnerLeaseId,
        slot: OwnerSlotDesc,
        route_epoch: u64,
    },
    TargetAborted,
    Error(OwnerTransferItemError),
}

#[derive(Default, Debug, Clone, PartialEq, Eq, Encode, Decode)]
pub struct OwnerSegmentTransferItemResp {
    pub op_id: Option<OwnerTransferOpId>,
    pub outcome: OwnerSegmentTransferOutcome,
}

#[derive(Default, Debug, Clone, Encode, Decode)]
pub struct OwnerSegmentTransferReq {
    pub items: Vec<OwnerSegmentTransferItem>,
}

impl MsgPackSerializePart for OwnerSegmentTransferReq {
    fn msg_id(&self) -> u32 {
        MsgId::OwnerSegmentTransferReq as u32
    }
}

impl RPCReq for OwnerSegmentTransferReq {
    type Resp = OwnerSegmentTransferResp;
}

#[derive(Default, Debug, Clone, Encode, Decode)]
pub struct OwnerSegmentTransferResp {
    pub items: Vec<OwnerSegmentTransferItemResp>,
    pub error_code: ErrorCode,
    pub error_json: String,
    pub server_process_us: i64,
}

impl MsgPackSerializePart for OwnerSegmentTransferResp {
    fn msg_id(&self) -> u32 {
        MsgId::OwnerSegmentTransferResp as u32
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn owner_segment_transfer_batch_wire_preserves_generation_and_operation_identity() {
        let coordinator = OwnerGeneration::new("coordinator", 17);
        let target = OwnerGeneration::new("target", 23);
        let operation = OwnerTransferOpId::new(
            coordinator.clone(),
            9,
            OwnerTransferOpKind::ReplicaAppend,
        );
        let request = OwnerSegmentTransferReq {
            items: vec![OwnerSegmentTransferItem::PrepareTarget {
                op_id: operation.clone(),
                expected_target: target.clone(),
                key: "key".to_string(),
                put_id: (101, 2),
                len: 4718592,
                disposition: OwnerTargetDisposition::GlobalShared,
                atomic_batch: None,
            }],
        };
        let decoded: OwnerSegmentTransferReq =
            bitcode::decode(&bitcode::encode(&request)).expect("decode owner transfer request");
        assert_eq!(decoded.items, request.items);
        assert_eq!(request.msg_id(), 3083);

        let response = OwnerSegmentTransferResp {
            items: vec![OwnerSegmentTransferItemResp {
                op_id: Some(operation),
                outcome: OwnerSegmentTransferOutcome::TargetPrepared {
                    lease_id: OwnerLeaseId {
                        owner: target.clone(),
                        sequence: 3,
                    },
                    slot: OwnerSlotDesc {
                        owner: target,
                        allocation_id: 7,
                        segment_offset: 4096,
                        capacity_bytes: 8192,
                        addr: 0x2000,
                        base_addr: 0x1000,
                        len: 5000,
                        segment_registration_epoch: 23,
                    },
                    state: OwnerTargetLeaseStateView::Prepared,
                },
            }],
            error_code: crate::rpcresp_kvresult_convert::msg_and_error::OK,
            error_json: String::new(),
            server_process_us: 11,
        };
        let decoded: OwnerSegmentTransferResp =
            bitcode::decode(&bitcode::encode(&response)).expect("decode owner transfer response");
        assert_eq!(decoded.items, response.items);
        assert_eq!(response.msg_id(), 3084);
    }
}
