"""
Visualization — Plots for Report
==================================
Generates publication-quality plots from experiment results.

Every plot answers a specific research question.
Consistent colors across all plots for readability.

RUN:   python -m app.plots
OUTPUT: results/plots/*.png
"""

import os
import csv
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from app.state_machine import DeviceMonitor, DeviceState, MonitorConfig
from app.baseline_monitor import BaselineMonitor
from app.digital_twin import DigitalTwin
from app.metrics import compute_metrics

# ── Consistent styling across all plots ──────────────────────────
# WHY fixed colors? So every plot uses the same color for the same state.
# The reader learns once that green=OK and red=FAULT, then can read
# every plot instantly. This is a data visualization best practice.

STATE_COLORS = {
    DeviceState.OK: "#2ecc71",              # Green
    DeviceState.STALE: "#f39c12",           # Orange
    DeviceState.OFFLINE_FAULT: "#e74c3c",   # Red
    DeviceState.RECOVERED: "#3498db",       # Blue
    DeviceState.SILENT: "#9b59b6",          # Purple
}

MONITOR_COLORS = {
    "proposed": "#2c3e50",  # Dark blue
    "baseline": "#95a5a6",  # Grey
}

PLOT_DIR = "results/plots"


def ensure_plot_dir():
    os.makedirs(PLOT_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# PLOT 1: Accuracy comparison bar chart (RQ1)
# ═══════════════════════════════════════════════════════════════════

def plot_accuracy_comparison(results: list[tuple], save: bool = True):
    """
    Side-by-side bar chart comparing accuracy of proposed vs baseline
    across all scenarios.

    WHY bar chart? Because we're comparing two discrete categories
    (proposed vs baseline) across multiple scenarios. Bar charts are
    the standard visualization for this type of comparison.
    """
    scenarios = [pm.scenario_name for pm, _ in results]
    proposed_acc = [pm.accuracy * 100 for pm, _ in results]
    baseline_acc = [bm.accuracy * 100 for _, bm in results]

    # Shorten scenario names for readability on x-axis
    short_names = [s.replace("_", "\n") for s in scenarios]

    x = np.arange(len(scenarios))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 5))
    bars1 = ax.bar(x - width/2, proposed_acc, width,
                   label="Proposed", color=MONITOR_COLORS["proposed"])
    bars2 = ax.bar(x + width/2, baseline_acc, width,
                   label="Baseline", color=MONITOR_COLORS["baseline"])

    ax.set_ylabel("Accuracy (%)")
    ax.set_title("State Inference Accuracy: Proposed vs Baseline (RQ1)")
    ax.set_xticks(x)
    ax.set_xticklabels(short_names, fontsize=8)
    ax.set_ylim(0, 110)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    # Add value labels on bars
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{bar.get_height():.0f}%", ha="center", fontsize=7)
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{bar.get_height():.0f}%", ha="center", fontsize=7)

    plt.tight_layout()

    if save:
        ensure_plot_dir()
        path = os.path.join(PLOT_DIR, "accuracy_comparison.png")
        plt.savefig(path, dpi=150)
        print(f"Saved: {path}")

    plt.close()

# ═══════════════════════════════════════════════════════════════════
# PLOT 2: False positives and negatives comparison (RQ1 + RQ2)
# ═══════════════════════════════════════════════════════════════════

def plot_fp_fn_comparison(results: list[tuple], save: bool = True):
    """
    Grouped bar chart showing FP and FN counts per scenario.
    Highlights where each monitor makes mistakes.
    """
    scenarios = [pm.scenario_name for pm, _ in results]
    short_names = [s.replace("_", "\n") for s in scenarios]

    proposed_fp = [pm.false_positives for pm, _ in results]
    proposed_fn = [pm.false_negatives for pm, _ in results]
    baseline_fp = [bm.false_positives for _, bm in results]
    baseline_fn = [bm.false_negatives for _, bm in results]

    x = np.arange(len(scenarios))
    width = 0.2

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.bar(x - 1.5*width, proposed_fp, width, label="Proposed FP",
           color=MONITOR_COLORS["proposed"], alpha=0.8)
    ax.bar(x - 0.5*width, proposed_fn, width, label="Proposed FN",
           color=MONITOR_COLORS["proposed"], alpha=0.4)
    ax.bar(x + 0.5*width, baseline_fp, width, label="Baseline FP",
           color=MONITOR_COLORS["baseline"], alpha=0.8)
    ax.bar(x + 1.5*width, baseline_fn, width, label="Baseline FN",
           color=MONITOR_COLORS["baseline"], alpha=0.4)

    ax.set_ylabel("Count (seconds)")
    ax.set_title("False Positives & False Negatives by Scenario (RQ1 + RQ2)")
    ax.set_xticks(x)
    ax.set_xticklabels(short_names, fontsize=8)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()

    if save:
        ensure_plot_dir()
        path = os.path.join(PLOT_DIR, "fp_fn_comparison.png")
        plt.savefig(path, dpi=150)
        print(f"Saved: {path}")

    plt.close()


# ═══════════════════════════════════════════════════════════════════
# PLOT 3: State timeline — inferred vs ground truth (RQ2)
# ═══════════════════════════════════════════════════════════════════

def plot_state_timeline(
    scenario, proposed: DeviceMonitor, baseline: BaselineMonitor,
    save: bool = True,
):
    """
    Three horizontal bars showing:
      1. Ground truth state over time
      2. Proposed monitor's inferred state
      3. Baseline monitor's inferred state

    WHY this plot? It's the most intuitive visual proof that your
    monitor works. An examiner sees green (OK) matching green (ground truth)
    and immediately understands "the monitor got it right."
    """
    # State to numeric mapping for plotting
    state_order = [
        DeviceState.OK,
        DeviceState.SILENT,
        DeviceState.STALE,
        DeviceState.RECOVERED,
        DeviceState.OFFLINE_FAULT,
    ]
    state_to_y = {s: i for i, s in enumerate(state_order)}

    # Sample states at 1-second intervals
    times = np.arange(0, scenario.duration, 1.0)

    truth_states = [scenario.get_true_state_at(t) for t in times]
    proposed_states = [proposed.get_state_at(t) for t in times]
    baseline_states = [baseline.get_state_at(t) for t in times]

    fig, axes = plt.subplots(3, 1, figsize=(14, 6), sharex=True)
    labels = ["Ground Truth", "Proposed Monitor", "Baseline Monitor"]
    all_states = [truth_states, proposed_states, baseline_states]

    for ax, label, states in zip(axes, labels, all_states):
        # Draw colored segments
        for i in range(len(times) - 1):
            color = STATE_COLORS.get(states[i], "#cccccc")
            ax.barh(0, 1, left=times[i], height=0.6, color=color)

        ax.set_ylabel(label, fontsize=9)
        ax.set_yticks([])
        ax.set_xlim(0, scenario.duration)

    axes[-1].set_xlabel("Time (seconds)")
    axes[0].set_title(
        f"State Timeline: {scenario.name} — {scenario.description}",
        fontsize=11,
    )

    # Shared legend
    patches = [
        mpatches.Patch(color=c, label=s.value)
        for s, c in STATE_COLORS.items()
    ]
    fig.legend(handles=patches, loc="lower center", ncol=5, fontsize=8)
    plt.subplots_adjust(bottom=0.15)
    plt.tight_layout(rect=[0, 0.08, 1, 1])

    if save:
        ensure_plot_dir()
        safe_name = scenario.name.replace(" ", "_")
        path = os.path.join(PLOT_DIR, f"timeline_{safe_name}.png")
        plt.savefig(path, dpi=150)
        print(f"Saved: {path}")

    plt.close()

# ═══════════════════════════════════════════════════════════════════
# PLOT 4: Trade-off curves (RQ3)
# ═══════════════════════════════════════════════════════════════════

def plot_tradeoff_curves(
    sweep_results: list[tuple[float, list[tuple]]],
    save: bool = True,
):
    """
    Line chart showing how accuracy changes as heartbeat interval increases.
    X-axis: heartbeat interval (telemetry rate)
    Y-axis: average accuracy

    WHY this plot? RQ3 asks about the trade-off between reducing telemetry
    and inference quality. This directly visualises that trade-off.
    """
    intervals = [r[0] for r in sweep_results]

    proposed_avg_acc = []
    baseline_avg_acc = []

    for _, results in sweep_results:
        p_accs = [pm.accuracy * 100 for pm, _ in results]
        b_accs = [bm.accuracy * 100 for _, bm in results]
        proposed_avg_acc.append(np.mean(p_accs))
        baseline_avg_acc.append(np.mean(b_accs))

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(intervals, proposed_avg_acc, "o-",
            color=MONITOR_COLORS["proposed"], label="Proposed", linewidth=2)
    ax.plot(intervals, baseline_avg_acc, "s--",
            color=MONITOR_COLORS["baseline"], label="Baseline", linewidth=2)

    ax.set_xlabel("Heartbeat Interval (seconds) — higher = less telemetry")
    ax.set_ylabel("Average Accuracy (%)")
    ax.set_title("Telemetry Rate vs Inference Accuracy (RQ3)")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_ylim(50, 105)

    plt.tight_layout()

    if save:
        ensure_plot_dir()
        path = os.path.join(PLOT_DIR, "tradeoff_curves.png")
        plt.savefig(path, dpi=150)
        print(f"Saved: {path}")

    plt.close()


# ═══════════════════════════════════════════════════════════════════
# MAIN — Generate all plots
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from app.run_experiments import run_all_experiments, run_parameter_sweep

    print("Generating plots...")
    ensure_plot_dir()

    config = MonitorConfig()
    twin = DigitalTwin(heartbeat_interval=30.0, seed=42)

    # ── Run experiments for standard comparison ──
    results = run_all_experiments()

    # Plot 1: Accuracy comparison
    plot_accuracy_comparison(results)

    # Plot 2: FP/FN comparison
    plot_fp_fn_comparison(results)

    # Plot 3: State timelines for key scenarios
    # Re-run to capture monitor objects (not just metrics)
    key_scenarios = [
        twin.scenario_suppression(),
        twin.scenario_hard_fault(),
        twin.scenario_flapping(),
        twin.scenario_dropout(),
    ]

    for scenario in key_scenarios:
        proposed = DeviceMonitor("device-001", config)
        baseline = BaselineMonitor("device-001", config)
        for e in scenario.events:
            proposed.process_event(e.event, e.timestamp)
            baseline.process_event(e.event, e.timestamp)
        plot_state_timeline(scenario, proposed, baseline)

    # Plot 4: Trade-off curves (RQ3)
    sweep = run_parameter_sweep(intervals=[15.0, 30.0, 60.0, 120.0])
    plot_tradeoff_curves(sweep)

    print(f"\nAll plots saved to {PLOT_DIR}/")