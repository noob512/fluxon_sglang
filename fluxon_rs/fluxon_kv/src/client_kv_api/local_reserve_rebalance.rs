use super::{ClientKvApiInner, ClientKvApiView, OwnerHotEvictionDispatch, OwnerSegmentAllocator};
use crate::client_seg_pool::ClientSegPoolAccessTrait;
use crate::master_seg_manager::msg_pack::SegmentAllocationAuthority;
use limit_thirdparty::tokio;
use std::{
    collections::BTreeSet,
    time::{Duration, Instant},
};

const OWNER_SEGMENT_REPORT_INTERVAL: Duration = Duration::from_secs(30);
const OWNER_LOCAL_RESERVE_DEFAULT_SOFT_WAIT_TIMEOUT: Duration = Duration::from_millis(10);
const OWNER_LOCAL_RESERVE_DEFAULT_HARD_TIMEOUT: Duration = Duration::from_secs(30);
const OWNER_SLOT_PRESSURE_INTERVAL: Duration = Duration::from_millis(10);
const OWNER_SLOT_PRESSURE_MIN_KICK_INTERVAL: Duration = Duration::from_millis(25);
const OWNER_SLOT_PRESSURE_INITIAL_COARSE_BYTES: u64 = 64 * 1024 * 1024;
// Bound one pressure round in bytes. Physical ownership is one complete segment.
const OWNER_SLOT_PRESSURE_MAX_EVICT_BYTES: u64 = 4 * 1024 * 1024 * 1024;

#[derive(Debug, Clone, Copy)]
struct ExpectedCapacityLayout {
    value_len: u64,
    slot_size: u64,
    payload_capacity_bytes: u64,
    physical_capacity_bytes: u64,
}

#[derive(Debug, Clone, Copy, Default)]
struct SlotPressureCapacity {
    accounting_slot_size: u64,
    allocatable_slots: u64,
    allocatable_bytes: u64,
    slot_unallocatable_bytes: u64,
    pending_size_classes: usize,
    initial_pop_bytes: u64,
}

#[derive(Debug, Clone, Copy)]
struct RebalanceSnapshot {
    used_bytes: u64,
    free_bytes: u64,
    largest_free_bytes: u64,
    pending_bytes: u64,
    largest_pending_slot_size: u64,
    accounting_slot_size: u64,
    allocatable_slots: u64,
    allocatable_bytes: u64,
    slot_unallocatable_bytes: u64,
    pending_size_classes: usize,
    pressure_initial_pop_bytes: u64,
    claim_progress_epoch: u64,
    physical_capacity_bytes: u64,
    local_target_bytes: u64,
}

fn expected_capacity_layout(
    value_len: u64,
    payload_capacity_bytes: u64,
    physical_capacity_bytes: u64,
) -> ExpectedCapacityLayout {
    let slot_size = crate::owner_segment_allocation_capacity_bytes(value_len)
        .expect("owner expected slot size must be config-validated");
    assert!(
        payload_capacity_bytes <= physical_capacity_bytes,
        "logical owner-local capacity must fit the physical segment"
    );
    ExpectedCapacityLayout {
        value_len,
        slot_size,
        payload_capacity_bytes,
        physical_capacity_bytes,
    }
}

fn configured_expected_capacity(inner: &ClientKvApiInner) -> Option<ExpectedCapacityLayout> {
    let expected = inner
        .test_spec_config
        .owner_local_reserve_expected_capacity
        .as_ref()?;
    Some(expected_capacity_layout(
        expected.value_len,
        expected.payload_capacity_bytes,
        inner.owner_local_reserve_physical_capacity_bytes,
    ))
}

async fn install_owner_segment_allocator(view: &ClientKvApiView) -> Result<(), String> {
    let inner = view.client_kv_api().inner();
    if inner.allocation_authority != SegmentAllocationAuthority::Owner {
        if inner.owner_hot_cache.is_some() {
            return Err(
                "owner-local Moka requires owner allocation authority for the complete segment"
                    .to_string(),
            );
        }
        return Ok(());
    }

    let segment = view
        .client_seg_pool()
        .cpu_mem_read_guard()
        .await
        .map_err(|err| format!("owner allocator cannot read the registered segment: {err}"))?;
    let base_addr = segment.allocated_addr;
    let segment_bytes = segment.allocated_size;
    drop(segment);
    if segment_bytes != inner.owner_local_reserve_physical_capacity_bytes {
        return Err(format!(
            "owner segment/config mismatch: segment_bytes={} configured_bytes={}",
            segment_bytes, inner.owner_local_reserve_physical_capacity_bytes
        ));
    }
    if segment_bytes == 0 || segment_bytes % crate::OWNER_SEGMENT_ALLOCATION_GRANULARITY_BYTES != 0
    {
        return Err(format!(
            "owner segment must be a non-zero multiple of {} bytes: segment_bytes={}",
            crate::OWNER_SEGMENT_ALLOCATION_GRANULARITY_BYTES,
            segment_bytes
        ));
    }

    let local_target_bytes = inner
        .owner_hot_cache
        .as_ref()
        .and_then(|cache| cache.max_capacity())
        .unwrap_or(segment_bytes);
    let expected_slot_size = configured_expected_capacity(inner).map(|layout| layout.slot_size);
    let self_info = view.cluster_manager().get_self_info();
    let registration_epoch = u64::try_from(self_info.node_start_time).map_err(|_| {
        format!(
            "owner segment registration epoch must be non-negative: owner={} node_start_time={}",
            self_info.id, self_info.node_start_time
        )
    })?;
    inner.owner_segment_allocator.lock().install_segment(
        crate::owner_segment::OwnerGeneration::new(
            self_info.id.to_string(),
            self_info.node_start_time,
        ),
        registration_epoch,
        base_addr,
        base_addr,
        segment_bytes,
        local_target_bytes,
        expected_slot_size,
    )?;
    tracing::info!(
        base_addr,
        segment_bytes,
        local_target_bytes,
        global_target_bytes = segment_bytes.saturating_sub(local_target_bytes),
        allocator_unit_bytes = crate::OWNER_SEGMENT_ALLOCATION_GRANULARITY_BYTES,
        allocator_max_metadata_nodes = 128 * 1024,
        "installed one allocator over the complete owner-authoritative DRAM segment"
    );
    Ok(())
}

fn slot_pressure_capacity(pool: &OwnerSegmentAllocator) -> SlotPressureCapacity {
    let slot_sizes = BTreeSet::from_iter(pool.pending_demand_by_slot_size.iter().filter_map(
        |(slot_size, count)| {
            (*count != 0 && pool.slot_size_has_failed_claim(*slot_size)).then_some(*slot_size)
        },
    ));
    let Some(accounting_slot_size) = pool
        .expected_slot_size
        .filter(|slot_size| slot_sizes.contains(slot_size))
        .or_else(|| slot_sizes.iter().next_back().copied())
    else {
        return SlotPressureCapacity::default();
    };
    let accounting_report = pool.allocatable_report(accounting_slot_size);
    let mut initial_pop_bytes = 0u64;
    for slot_size in slot_sizes {
        let report = if slot_size == accounting_slot_size {
            accounting_report
        } else {
            pool.allocatable_report(slot_size)
        };
        let pending_slots = u64::try_from(pool.pending_demand_slots(slot_size)).unwrap_or(u64::MAX);
        if pending_slots > report.allocatable_slots {
            let missing_bytes = pending_slots
                .saturating_sub(report.allocatable_slots)
                .saturating_mul(slot_size);
            let coarse_bytes = pending_slots
                .saturating_mul(slot_size)
                .min(OWNER_SLOT_PRESSURE_INITIAL_COARSE_BYTES);
            // Size classes view the same free extents, so the maximum shortage
            // is the one shared pressure budget. Summing would double count.
            initial_pop_bytes = initial_pop_bytes.max(missing_bytes.max(coarse_bytes));
        }
    }
    SlotPressureCapacity {
        accounting_slot_size,
        allocatable_slots: accounting_report.allocatable_slots,
        allocatable_bytes: accounting_report.allocatable_bytes,
        slot_unallocatable_bytes: accounting_report.slot_unallocatable_bytes,
        pending_size_classes: pool
            .pending_demand_by_slot_size
            .values()
            .filter(|count| **count != 0)
            .count(),
        initial_pop_bytes,
    }
}

fn snapshot_rebalance(inner: &ClientKvApiInner) -> RebalanceSnapshot {
    let pool = inner.owner_segment_allocator.lock();
    let pressure = slot_pressure_capacity(&pool);
    RebalanceSnapshot {
        used_bytes: pool.total_used_bytes(),
        free_bytes: pool.total_free_bytes(),
        largest_free_bytes: pool.largest_free_bytes(),
        pending_bytes: pool.total_pending_bytes(),
        largest_pending_slot_size: pool.largest_pending_slot_size(),
        accounting_slot_size: pressure.accounting_slot_size,
        allocatable_slots: pressure.allocatable_slots,
        allocatable_bytes: pressure.allocatable_bytes,
        slot_unallocatable_bytes: pressure.slot_unallocatable_bytes,
        pending_size_classes: pressure.pending_size_classes,
        pressure_initial_pop_bytes: pressure.initial_pop_bytes,
        claim_progress_epoch: pool.claim_progress_epoch,
        physical_capacity_bytes: pool.physical_capacity_bytes(),
        local_target_bytes: pool.local_target_bytes,
    }
}

pub(crate) fn owner_local_reserve_timeout_config(inner: &ClientKvApiInner) -> (Duration, Duration) {
    let soft_wait_timeout = inner
        .test_spec_config
        .owner_local_reserve_soft_wait_timeout_ms
        .map(Duration::from_millis)
        .unwrap_or(OWNER_LOCAL_RESERVE_DEFAULT_SOFT_WAIT_TIMEOUT);
    let hard_timeout = inner
        .test_spec_config
        .owner_local_reserve_hard_timeout_ms
        .map(Duration::from_millis)
        .unwrap_or(OWNER_LOCAL_RESERVE_DEFAULT_HARD_TIMEOUT);
    (soft_wait_timeout, hard_timeout)
}

fn report_owner_segment_state(inner: &ClientKvApiInner) {
    let snapshot = snapshot_rebalance(inner);
    let expected = configured_expected_capacity(inner);
    let moka_weighted_bytes = inner
        .owner_hot_cache
        .as_ref()
        .map(|cache| cache.weighted_size())
        .unwrap_or(0);
    tracing::info!(
        physical_capacity_bytes = snapshot.physical_capacity_bytes,
        local_target_bytes = snapshot.local_target_bytes,
        global_target_bytes = snapshot
            .physical_capacity_bytes
            .saturating_sub(snapshot.local_target_bytes),
        expected_value_len = expected.map(|layout| layout.value_len).unwrap_or(0),
        expected_slot_size = expected.map(|layout| layout.slot_size).unwrap_or(0),
        logical_payload_capacity_bytes = expected
            .map(|layout| layout.payload_capacity_bytes)
            .unwrap_or(0),
        configured_physical_capacity_bytes = expected
            .map(|layout| layout.physical_capacity_bytes)
            .unwrap_or(0),
        moka_weighted_bytes,
        used_bytes = snapshot.used_bytes,
        free_bytes = snapshot.free_bytes,
        largest_free_bytes = snapshot.largest_free_bytes,
        pending_bytes = snapshot.pending_bytes,
        largest_pending_slot_size = snapshot.largest_pending_slot_size,
        accounting_slot_size = snapshot.accounting_slot_size,
        allocatable_slots = snapshot.allocatable_slots,
        allocatable_bytes = snapshot.allocatable_bytes,
        slot_unallocatable_bytes = snapshot.slot_unallocatable_bytes,
        pending_size_classes = snapshot.pending_size_classes,
        pressure_initial_pop_bytes = snapshot.pressure_initial_pop_bytes,
        claim_progress_epoch = snapshot.claim_progress_epoch,
        "owner segment allocator state"
    );
}

pub fn spawn_owner_local_reserve_rebalance_actor(view: ClientKvApiView) {
    let view_task = view.clone();
    view.spawn("owner_segment_allocator_actor", async move {
        if let Err(err) = install_owner_segment_allocator(&view_task).await {
            tracing::error!(error = %err, "failed to initialize owner segment allocator");
            return;
        }
        let shutdown_poller = view_task.register_shutdown_poller();
        let mut shutdown_waiter = view_task.register_shutdown_waiter();
        let mut tick = tokio::time::interval(OWNER_SEGMENT_REPORT_INTERVAL);
        loop {
            tokio::select! {
                biased;
                _ = shutdown_waiter.wait() => return,
                _ = tick.tick() => {}
            }
            if !shutdown_poller.is_running() {
                return;
            }
            report_owner_segment_state(view_task.client_kv_api().inner());
        }
    });
}

fn owner_slot_pressure_round_bytes(initial_bytes: u64, round: u32) -> u64 {
    let multiplier = 1u64.checked_shl(round.min(63)).unwrap_or(u64::MAX);
    initial_bytes
        .saturating_mul(multiplier)
        .min(OWNER_SLOT_PRESSURE_MAX_EVICT_BYTES)
}

fn owner_slot_pressure_selected_fence_bytes(inner: &ClientKvApiInner) -> u64 {
    inner
        .owner_hot_counters
        .source_eviction_selected_bytes
        .load(std::sync::atomic::Ordering::Acquire)
}

#[derive(Debug, Clone, Copy, Default, Eq, PartialEq)]
struct OwnerPressureBackoff {
    round: u32,
    base_bytes: u64,
    observed_claim_progress_epoch: u64,
}

impl OwnerPressureBackoff {
    fn reset(&mut self, claim_progress_epoch: u64) {
        self.round = 0;
        self.base_bytes = 0;
        self.observed_claim_progress_epoch = claim_progress_epoch;
    }

    fn sync_claim_progress(&mut self, claim_progress_epoch: u64) {
        if self.observed_claim_progress_epoch != claim_progress_epoch {
            self.reset(claim_progress_epoch);
        }
    }

    fn request_bytes(&mut self, initial_bytes: u64) -> u64 {
        self.base_bytes = self.base_bytes.max(initial_bytes);
        owner_slot_pressure_round_bytes(self.base_bytes, self.round)
    }

    fn finish_round(&mut self, selected_bytes: u64) {
        if selected_bytes != 0 {
            self.round = self.round.saturating_add(1);
        }
    }
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
enum OwnerPressureBatchDispatchError {
    DispatcherClosed,
    CompletionDropped,
}

async fn finish_owner_pressure_batch(
    tx: &limit_thirdparty::tokio::sync::ampsc::UnboundedSender<OwnerHotEvictionDispatch>,
    selected_bytes: u64,
) -> Result<(), OwnerPressureBatchDispatchError> {
    let (completion, completed) = ::tokio::sync::oneshot::channel();
    tx.send(OwnerHotEvictionDispatch::EndPressure {
        selected_bytes,
        completion,
    })
    .map_err(|_| OwnerPressureBatchDispatchError::DispatcherClosed)?;
    completed
        .await
        .map_err(|_| OwnerPressureBatchDispatchError::CompletionDropped)
}

pub fn spawn_owner_slot_pressure_actor(view: ClientKvApiView) {
    let view_task = view.clone();
    view.spawn("owner_slot_pressure_actor", async move {
        let shutdown_poller = view_task.register_shutdown_poller();
        let mut shutdown_waiter = view_task.register_shutdown_waiter();
        let notify = view_task
            .client_kv_api()
            .inner()
            .owner_local_reserve_rebalance_notify();
        let mut tick = tokio::time::interval(OWNER_SLOT_PRESSURE_INTERVAL);
        let mut last_kick_at: Option<Instant> = None;
        let mut backoff = OwnerPressureBackoff::default();

        loop {
            tokio::select! {
                biased;
                _ = shutdown_waiter.wait() => return,
                _ = tick.tick() => {},
                _ = notify.notified() => {}
            }
            if !shutdown_poller.is_running() {
                return;
            }

            let inner = view_task.client_kv_api().inner();
            let snapshot = snapshot_rebalance(inner);
            backoff.sync_claim_progress(snapshot.claim_progress_epoch);
            let initial_bytes = snapshot.pressure_initial_pop_bytes;
            if initial_bytes == 0 {
                backoff.reset(snapshot.claim_progress_epoch);
                continue;
            }
            if owner_slot_pressure_selected_fence_bytes(inner) != 0 {
                continue;
            }
            if last_kick_at
                .is_some_and(|last| last.elapsed() < OWNER_SLOT_PRESSURE_MIN_KICK_INTERVAL)
            {
                continue;
            }
            let pressure_round = backoff.round;
            let requested_bytes = backoff.request_bytes(initial_bytes);
            let Some(cache) = inner.owner_hot_cache.clone() else {
                continue;
            };
            let _selection_guard = inner.owner_hot_selection_lock.lock().await;
            if inner
                .owner_hot_eviction_tx
                .send(OwnerHotEvictionDispatch::BeginPressure { requested_bytes })
                .is_err()
            {
                return;
            }
            let selected_bytes = limit_thirdparty::tokio::task::spawn_blocking(move || {
                cache.evict_some(requested_bytes)
            })
            .await
            .unwrap_or(0);
            last_kick_at = Some(Instant::now());
            let result = tokio::select! {
                biased;
                _ = shutdown_waiter.wait() => return,
                result = finish_owner_pressure_batch(&inner.owner_hot_eviction_tx, selected_bytes) => result,
            };
            if let Err(err) = result {
                tracing::warn!(?err, requested_bytes, selected_bytes, "owner pressure batch failed");
                return;
            }
            backoff.finish_round(selected_bytes);
            tracing::debug!(
                requested_bytes,
                selected_bytes,
                pressure_round,
                pressure_initial_pop_bytes = initial_bytes,
                accounting_slot_size = snapshot.accounting_slot_size,
                raw_free_bytes = snapshot.free_bytes,
                allocatable_slots = snapshot.allocatable_slots,
                allocatable_bytes = snapshot.allocatable_bytes,
                slot_unallocatable_bytes = snapshot.slot_unallocatable_bytes,
                pending_bytes = snapshot.pending_bytes,
                pending_size_classes = snapshot.pending_size_classes,
                claim_progress_epoch = snapshot.claim_progress_epoch,
                "owner segment pressure completed exponential single-KV eviction round"
            );
        }
    });
}

pub async fn wait_owner_local_reserve_ready(
    inner: &ClientKvApiInner,
    slot_size: u64,
    key_count: usize,
    soft_wait_timeout: Duration,
    hard_deadline: Instant,
) -> bool {
    let notify = inner.owner_local_reserve_rebalance_notify();
    let mut shutdown_waiter = inner.view.register_shutdown_waiter();
    let required_slots = u64::try_from(key_count).unwrap_or(u64::MAX);
    loop {
        let notified = notify.notified();
        if inner
            .owner_segment_allocator
            .lock()
            .allocatable_report(slot_size)
            .allocatable_slots
            >= required_slots
        {
            return true;
        }
        let Some(remaining_hard) = hard_deadline.checked_duration_since(Instant::now()) else {
            return false;
        };
        let wait_budget = remaining_hard.min(soft_wait_timeout);
        tokio::select! {
            _ = shutdown_waiter.wait() => return false,
            _ = tokio::time::sleep(wait_budget) => {
                notify.notify_waiters();
            }
            _ = notified => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pressure_backoff_is_byte_bounded() {
        assert_eq!(
            owner_slot_pressure_round_bytes(64 * 1024 * 1024, 0),
            64 * 1024 * 1024
        );
        assert_eq!(
            owner_slot_pressure_round_bytes(64 * 1024 * 1024, 3),
            512 * 1024 * 1024
        );
        assert_eq!(
            owner_slot_pressure_round_bytes(64 * 1024 * 1024, 20),
            4 * 1024 * 1024 * 1024
        );
    }

    #[test]
    fn expected_layout_keeps_logical_and_physical_bytes_separate() {
        let layout = expected_capacity_layout(
            4_718_592,
            100 * 1024 * 1024 * 1024,
            128 * 1024 * 1024 * 1024,
        );
        assert_eq!(layout.slot_size, 4_718_592);
        assert_eq!(layout.payload_capacity_bytes, 100 * 1024 * 1024 * 1024);
        assert_eq!(layout.physical_capacity_bytes, 128 * 1024 * 1024 * 1024);
    }
}
