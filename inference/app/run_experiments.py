"""
Experiment Runner
==================
Runs all digital twin scenarios through both monitors and collects metrics.

RUN:   python -m app.run_experiments
OUTPUT: results/summary.csv + printed comparison table
"""

import csv
import os
from app.state_machine import DeviceMonitor, MonitorConfig
from app.baseline_monitor import BaselineMonitor
from app.digital_twin import DigitalTwin
from app.metrics import compute_metrics, MetricsResult


def run_single_experiment(
    scenario, config: MonitorConfig
) -> tuple[MetricsResult, MetricsResult]:
    """Run one scenario through both monitors, return both metrics."""

    proposed = DeviceMonitor("device-001", config)
    baseline = BaselineMonitor("device-001", config)

    # Feed the SAME events to both monitors
    for e in scenario.events:
        proposed.process_event(e.event, e.timestamp)
        baseline.process_event(e.event, e.timestamp)

    pm = compute_metrics(proposed, scenario)
    bm = compute_metrics(baseline, scenario)

    return pm, bm


def run_all_experiments(
    heartbeat_interval: float = 30.0,
    seed: int = 42,
) -> list[tuple[MetricsResult, MetricsResult]]:
    """Run all 6 scenarios and return paired metrics."""

    config = MonitorConfig(heartbeat_interval_s=heartbeat_interval)
    twin = DigitalTwin(heartbeat_interval=heartbeat_interval, seed=seed)

    results = []
    for scenario in twin.all_scenarios():
        pm, bm = run_single_experiment(scenario, config)
        results.append((pm, bm))

    return results


def run_parameter_sweep(
    intervals: list[float] = None,
    seed: int = 42,
) -> list[tuple[float, list[tuple[MetricsResult, MetricsResult]]]]:
    """
    RQ3: Vary heartbeat interval and measure trade-offs.
    Returns list of (interval, experiment_results) pairs.
    """
    if intervals is None:
        intervals = [15.0, 30.0, 60.0, 120.0]

    sweep_results = []
    for interval in intervals:
        results = run_all_experiments(heartbeat_interval=interval, seed=seed)
        sweep_results.append((interval, results))

    return sweep_results


def print_comparison_table(results: list[tuple[MetricsResult, MetricsResult]]):
    """Print a formatted comparison table to the console."""

    print(f"\n{'='*90}")
    print(f"{'SCENARIO':<28} {'MONITOR':<10} {'ACCURACY':>8} {'LATENCY':>8} {'FP':>5} {'FN':>5} {'TRANS':>6}")
    print(f"{'-'*90}")

    for pm, bm in results:
        # Proposed
        lat_p = f"{pm.fault_detection_latency:.0f}s" if pm.fault_detection_latency >= 0 else "N/A"
        print(f"{pm.scenario_name:<28} {'proposed':<10} {pm.accuracy:>7.1%} {lat_p:>8} {pm.false_positives:>5} {pm.false_negatives:>5} {pm.total_transitions:>6}")

        # Baseline
        lat_b = f"{bm.fault_detection_latency:.0f}s" if bm.fault_detection_latency >= 0 else "N/A"
        print(f"{'':<28} {'baseline':<10} {bm.accuracy:>7.1%} {lat_b:>8} {bm.false_positives:>5} {bm.false_negatives:>5} {bm.total_transitions:>6}")

        print(f"{'-'*90}")


def save_to_csv(
    results: list[tuple[MetricsResult, MetricsResult]],
    filepath: str = "results/summary.csv",
):
    """Save metrics to CSV for use in plots and the report."""

    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    rows = []
    for pm, bm in results:
        for m in [pm, bm]:
            rows.append({
                "scenario": m.scenario_name,
                "monitor": m.monitor_type,
                "accuracy": round(m.accuracy, 4),
                "fault_detection_latency": round(m.fault_detection_latency, 2),
                "false_positives": m.false_positives,
                "false_negatives": m.false_negatives,
                "total_transitions": m.total_transitions,
                "total_samples": m.total_samples,
                "matched_samples": m.matched_samples,
            })

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nResults saved to {filepath}")


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running all experiments...")
    print("=" * 90)

    results = run_all_experiments()
    print_comparison_table(results)
    save_to_csv(results)

    print("\nDone. Use 'python -m app.plots' to generate visualisations.")
