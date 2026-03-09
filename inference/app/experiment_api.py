"""
Experiment API — REST Endpoints for Dashboard
================================================
Exposes the digital twin experiments via REST so ThingsBoard
HTML widgets can fetch and render results without running CLI commands.

Endpoints:
  GET /experiments/scenarios   — List available scenarios
  GET /experiments/summary     — Run all 7 scenarios, return metrics table
  GET /experiments/timeline    — Run one scenario, return tick-by-tick states
  GET /experiments/sweep       — RQ3: Vary heartbeat interval, show tradeoffs
  GET /experiments/telemetry-cost — Telemetry volume per interval
"""

import logging
from fastapi import APIRouter, Query
from app.state_machine import DeviceMonitor, DeviceState, MonitorConfig
from app.baseline_monitor import BaselineMonitor
from app.digital_twin import DigitalTwin
from app.metrics import compute_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/scenarios")
def list_scenarios():
    """
    List all available digital twin scenarios.
    Used by the dashboard to populate a scenario selector dropdown.
    """
    twin = DigitalTwin(heartbeat_interval=30.0, seed=42)
    scenarios = []
    for i, s in enumerate(twin.all_scenarios()):
        scenarios.append({
            "id": i,
            "name": s.name,
            "description": s.description,
            "duration": s.duration,
        })
    return {"scenarios": scenarios}


@router.get("/summary")
def run_summary(
    heartbeat_interval: float = Query(30.0, description="Heartbeat interval in seconds"),
    seed: int = Query(42, description="Random seed for reproducibility"),
):
    """
    Run ALL scenarios through both monitors and return comparison metrics.

    This is the core evidence table for the capstone:
      - Proposed vs baseline accuracy per scenario
      - False positives, false negatives
      - Detection latency

    Returns JSON that the TB HTML widget renders as a comparison table.
    """
    config = MonitorConfig(heartbeat_interval_s=heartbeat_interval)
    twin = DigitalTwin(heartbeat_interval=heartbeat_interval, seed=seed)

    results = []
    for scenario in twin.all_scenarios():
        proposed = DeviceMonitor("device-001", config)
        baseline = BaselineMonitor("device-001", config)

        for e in scenario.events:
            proposed.process_event(e.event, e.timestamp)
            baseline.process_event(e.event, e.timestamp)

        pm = compute_metrics(proposed, scenario)
        bm = compute_metrics(baseline, scenario)

        results.append({
            "scenario": scenario.name,
            "description": scenario.description,
            "proposed": {
                "accuracy": round(pm.accuracy * 100, 1),
                "false_positives": pm.false_positives,
                "false_negatives": pm.false_negatives,
                "detection_latency": round(pm.fault_detection_latency, 1),
                "transitions": pm.total_transitions,
            },
            "baseline": {
                "accuracy": round(bm.accuracy * 100, 1),
                "false_positives": bm.false_positives,
                "false_negatives": bm.false_negatives,
                "detection_latency": round(bm.fault_detection_latency, 1),
                "transitions": bm.total_transitions,
            },
        })

    return {
        "config": {
            "heartbeat_interval": heartbeat_interval,
            "seed": seed,
        },
        "results": results,
    }


@router.get("/timeline")
def run_timeline(
    scenario_id: int = Query(0, description="Scenario index (0-6)"),
    heartbeat_interval: float = Query(30.0, description="Heartbeat interval"),
    seed: int = Query(42, description="Random seed"),
    sample_interval: float = Query(1.0, description="Sample every N seconds"),
):
    """
    Run ONE scenario and return tick-by-tick state data for both monitors.

    Returns three timelines at every sample point:
      - ground_truth: what ACTUALLY happened
      - proposed: what the FSM monitor inferred
      - baseline: what the simple timeout monitor inferred

    The TB HTML widget renders these as side-by-side colored bands.
    """
    config = MonitorConfig(heartbeat_interval_s=heartbeat_interval)
    twin = DigitalTwin(heartbeat_interval=heartbeat_interval, seed=seed)
    scenarios = twin.all_scenarios()

    if scenario_id < 0 or scenario_id >= len(scenarios):
        return {"error": f"Invalid scenario_id. Must be 0-{len(scenarios)-1}"}

    scenario = scenarios[scenario_id]

    # Run both monitors on the same events
    proposed = DeviceMonitor("device-001", config)
    baseline = BaselineMonitor("device-001", config)

    for e in scenario.events:
        proposed.process_event(e.event, e.timestamp)
        baseline.process_event(e.event, e.timestamp)

    # Sample state at regular intervals
    timeline = []
    t = 0.0
    while t < scenario.duration:
        timeline.append({
            "t": round(t, 1),
            "truth": scenario.get_true_state_at(t).value,
            "proposed": proposed.get_state_at(t).value,
            "baseline": baseline.get_state_at(t).value,
        })
        t += sample_interval

    return {
        "scenario": {
            "id": scenario_id,
            "name": scenario.name,
            "description": scenario.description,
            "duration": scenario.duration,
        },
        "timeline": timeline,
    }


@router.get("/sweep")
def run_parameter_sweep(
    seed: int = Query(42, description="Random seed for reproducibility"),
):
    """
    RQ3: Vary heartbeat interval and measure the tradeoff.

    Runs ALL 7 scenarios at each interval (15s, 30s, 60s, 120s)
    through both monitors. Returns average accuracy and total FP/FN
    per interval so the dashboard can render tradeoff curves.

    KEY INSIGHT: As heartbeat interval increases (less telemetry),
    detection latency increases but telemetry cost drops. The question
    is: where is the sweet spot?
    """
    intervals = [15.0, 30.0, 60.0, 120.0]
    sweep = []

    for interval in intervals:
        config = MonitorConfig(heartbeat_interval_s=interval)
        twin = DigitalTwin(heartbeat_interval=interval, seed=seed)

        proposed_accuracies = []
        baseline_accuracies = []
        proposed_fp_total = 0
        baseline_fp_total = 0
        proposed_fn_total = 0
        baseline_fn_total = 0
        proposed_latencies = []
        baseline_latencies = []

        for scenario in twin.all_scenarios():
            proposed = DeviceMonitor("device-001", config)
            baseline = BaselineMonitor("device-001", config)

            for e in scenario.events:
                proposed.process_event(e.event, e.timestamp)
                baseline.process_event(e.event, e.timestamp)

            pm = compute_metrics(proposed, scenario)
            bm = compute_metrics(baseline, scenario)

            proposed_accuracies.append(pm.accuracy)
            baseline_accuracies.append(bm.accuracy)
            proposed_fp_total += pm.false_positives
            baseline_fp_total += bm.false_positives
            proposed_fn_total += pm.false_negatives
            baseline_fn_total += bm.false_negatives

            if pm.fault_detection_latency >= 0:
                proposed_latencies.append(pm.fault_detection_latency)
            if bm.fault_detection_latency >= 0:
                baseline_latencies.append(bm.fault_detection_latency)

        # Telemetry volume calculation for this interval
        messages_per_hour = 3600 / interval
        # Typical ESP32 heartbeat payload: ~80 bytes JSON + ~20 bytes MQTT overhead
        bytes_per_message = 100
        bytes_per_hour = messages_per_hour * bytes_per_message

        sweep.append({
            "interval": interval,
            "proposed": {
                "avg_accuracy": round(sum(proposed_accuracies) / len(proposed_accuracies) * 100, 1),
                "total_fp": proposed_fp_total,
                "total_fn": proposed_fn_total,
                "avg_latency": round(sum(proposed_latencies) / len(proposed_latencies), 1) if proposed_latencies else -1,
            },
            "baseline": {
                "avg_accuracy": round(sum(baseline_accuracies) / len(baseline_accuracies) * 100, 1),
                "total_fp": baseline_fp_total,
                "total_fn": baseline_fn_total,
                "avg_latency": round(sum(baseline_latencies) / len(baseline_latencies), 1) if baseline_latencies else -1,
            },
            "telemetry": {
                "messages_per_hour": round(messages_per_hour, 1),
                "bytes_per_hour": round(bytes_per_hour),
                "reduction_vs_15s": round((1 - (messages_per_hour / (3600 / 15))) * 100, 1),
            },
        })

    return {
        "seed": seed,
        "intervals": [s["interval"] for s in sweep],
        "sweep": sweep,
    }


@router.get("/telemetry-cost")
def telemetry_cost():
    """
    Telemetry volume comparison across heartbeat intervals.

    Shows messages/hour, bytes/hour, and reduction percentage.
    This answers the "cost" side of RQ3's cost-quality tradeoff.

    Calculation basis:
      - Each heartbeat message: ~100 bytes (80 JSON + 20 MQTT overhead)
      - Payload: {"uptime_ms":12345,"rssi_dbm":-58,"ldr_raw":1024,"ldr_v":1.234}
      - No additional telemetry beyond heartbeat (minimal design)
    """
    intervals = [15.0, 30.0, 60.0, 120.0]
    baseline_interval = 15.0
    baseline_msgs = 3600 / baseline_interval

    costs = []
    for interval in intervals:
        msgs = 3600 / interval
        bytes_per_msg = 100
        costs.append({
            "interval_s": interval,
            "messages_per_hour": round(msgs, 1),
            "bytes_per_hour": round(msgs * bytes_per_msg),
            "kb_per_hour": round(msgs * bytes_per_msg / 1024, 2),
            "mb_per_day": round(msgs * bytes_per_msg * 24 / (1024 * 1024), 3),
            "reduction_pct": round((1 - msgs / baseline_msgs) * 100, 1),
        })

    return {
        "basis": {
            "bytes_per_message": 100,
            "payload_example": '{"uptime_ms":12345,"rssi_dbm":-58,"ldr_raw":1024,"ldr_v":1.234}',
        },
        "costs": costs,
    }