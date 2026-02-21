"""
Metrics Engine
===============
Computes evaluation measures by comparing inferred state timelines
against ground-truth timelines from the digital twin.

All metrics use TIME-ALIGNED comparison: we sample the inferred state
and ground truth at regular intervals (every 1 second by default) and
compare them point by point. This avoids bias from uneven event spacing.
"""

from dataclasses import dataclass, field
from app.state_machine import DeviceState, DeviceMonitor, MonitorConfig
from app.baseline_monitor import BaselineMonitor
from app.digital_twin import Scenario


@dataclass
class MetricsResult:
    """All evaluation measures for one monitor on one scenario."""
    scenario_name: str
    monitor_type: str           # "proposed" or "baseline"

    # Core metrics
    accuracy: float             # 0.0 to 1.0 — proportion of time states match
    fault_detection_latency: float  # Seconds from true fault to first correct detection
    false_positives: int        # Times inferred STALE/FAULT during OK/SILENT
    false_negatives: int        # Times inferred OK during FAULT
    total_transitions: int      # How many state changes the monitor made

    # Detail
    total_samples: int          # Total time samples compared
    matched_samples: int        # Samples where inferred == ground truth


def compute_metrics(
    monitor,
    scenario: Scenario,
    sample_interval: float = 1.0,
) -> MetricsResult:
    """
    Compare a monitor's inferred timeline against scenario ground truth.

    HOW IT WORKS:
      1. Walk through time from 0 to scenario.duration in 1-second steps
      2. At each step, ask: "What did the monitor think?" vs "What was true?"
      3. Count matches, mismatches, FPs, FNs

    WHY 1-second sampling?
      Because events happen at irregular intervals (every 30s, with jitter).
      Sampling at a fixed rate gives every second of the scenario equal weight.
      Without this, a 5-minute FAULT period and a 5-second jitter blip would
      count equally (one mismatch each), which distorts accuracy.

    Args:
        monitor: A DeviceMonitor or BaselineMonitor (already processed events)
        scenario: The scenario with ground truth
        sample_interval: How often to sample (seconds)
    """
    monitor_type = "proposed" if isinstance(
        monitor, DeviceMonitor) else "baseline"

    matched = 0
    total = 0
    fp = 0
    fn = 0
    fault_detection_latency = -1.0  # -1 means no fault in scenario

    # Track when ground truth first enters FAULT
    true_fault_start = None
    for seg in scenario.ground_truth:
        if seg.state == DeviceState.OFFLINE_FAULT:
            true_fault_start = seg.start
            break

    # Track when monitor first correctly detects FAULT
    first_correct_fault = None

    t = 0.0
    while t < scenario.duration:
        true_state = scenario.get_true_state_at(t)
        inferred_state = monitor.get_state_at(t)

        total += 1

        # ── Accuracy: do they match? ──
        # RECOVERED is treated as acceptable during FAULT ground truth
        # because the monitor is acknowledging the problem
        if _states_match(inferred_state, true_state):
            matched += 1
        else:
            # ── False positive: monitor says bad, truth says fine ──
            if true_state in (DeviceState.OK, DeviceState.SILENT):
                if inferred_state in (DeviceState.STALE, DeviceState.OFFLINE_FAULT):
                    fp += 1

            # ── False negative: monitor says fine, truth says bad ──
            if true_state == DeviceState.OFFLINE_FAULT:
                if inferred_state == DeviceState.OK:
                    fn += 1

        # ── Fault detection latency ──
        if (true_fault_start is not None
                and first_correct_fault is None
                and inferred_state in (DeviceState.OFFLINE_FAULT, DeviceState.STALE)
                and t >= true_fault_start):
            first_correct_fault = t

        t += sample_interval

    # Calculate final metrics
    accuracy = matched / total if total > 0 else 0.0

    if true_fault_start is not None and first_correct_fault is not None:
        fault_detection_latency = first_correct_fault - true_fault_start
    elif true_fault_start is not None:
        fault_detection_latency = scenario.duration - true_fault_start  # Never detected

    return MetricsResult(
        scenario_name=scenario.name,
        monitor_type=monitor_type,
        accuracy=accuracy,
        fault_detection_latency=fault_detection_latency,
        false_positives=fp,
        false_negatives=fn,
        total_transitions=len(monitor.transitions),
        total_samples=total,
        matched_samples=matched,
    )


def _states_match(inferred: DeviceState, truth: DeviceState) -> bool:
    """
    Check if inferred state is acceptable given ground truth.

    WHY not just ==?
    Because some states are "close enough":
      - RECOVERED during a FAULT period is acceptable (monitor knows something's wrong)
      - STALE during early FAULT is acceptable (monitor is escalating, just hasn't reached FAULT yet)
      - SILENT matches SILENT (suppression correctly recognised)
    """
    if inferred == truth:
        return True

    # RECOVERED is acceptable during FAULT (acknowledges the problem)
    if truth == DeviceState.OFFLINE_FAULT and inferred == DeviceState.RECOVERED:
        return True

    # STALE is acceptable during FAULT (monitor is escalating)
    if truth == DeviceState.OFFLINE_FAULT and inferred == DeviceState.STALE:
        return True

    # STALE is acceptable during STALE ground truth
    # (already handled by == above, but explicit for clarity)

    return False
