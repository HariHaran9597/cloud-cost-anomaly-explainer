"""Reproducible event-level evaluation on a held-out synthetic seed set."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.csv_data import BillingRow
from app.detector import analyze

ROOT = Path(__file__).resolve().parents[1]
SEEDS = range(3100, 3140)  # Reserved evaluation seeds; not used to tune thresholds.
SCENARIOS = ("normal", "spike", "sustained", "noisy")
N_DAYS = 90


def make_scenario(seed: int, scenario: str) -> tuple[list[BillingRow], list[dict]]:
    rng = random.Random(seed)
    start = date(2025, 1, 1)
    bases = {"Compute": 32.0, "Storage": 9.0, "Database": 17.0, "Egress": 6.0}
    labels = []
    if scenario == "spike":
        labels.append({"start": 48, "end": 48, "service": "Egress", "cause": "spike"})
    elif scenario == "sustained":
        labels.append({"start": 54, "end": 59, "service": "Database", "cause": "sustained_increase"})
    rows = []
    for offset in range(N_DAYS):
        day = start + timedelta(days=offset)
        for service, base in bases.items():
            spread = 0.22 if scenario == "noisy" else 0.05
            amount = base * (1 + rng.uniform(-spread, spread))
            for label in labels:
                if label["start"] <= offset <= label["end"] and service == label["service"]:
                    amount += 26 if label["cause"] == "spike" else 30
            rows.append(BillingRow(day, service, service + " usage", "eval", "test-region", "platform", Decimal(f"{amount:.2f}"), "USD"))
    return rows, labels


def overlap(alert: dict, label: dict, start: date) -> bool:
    a0, a1 = date.fromisoformat(alert["start_date"]), date.fromisoformat(alert["end_date"])
    l0, l1 = start + timedelta(days=label["start"]), start + timedelta(days=label["end"])
    return a0 <= l1 and l0 <= a1


def evaluate_detector():
    tp = fp = fn = 0
    delays = []
    attribution_correct = attribution_total = 0
    by_scenario = {}
    for scenario in SCENARIOS:
        s_tp = s_fp = s_fn = s_attr = s_attr_total = 0
        for seed in SEEDS:
            rows, labels = make_scenario(seed, scenario)
            result = analyze(rows, f"eval-{scenario}-{seed}")
            alerts = result["alerts"][:20]
            start = date(2025, 1, 1)
            matched_alerts = set()
            for label in labels:
                candidates = [(i, alert) for i, alert in enumerate(alerts) if overlap(alert, label, start)]
                if candidates:
                    index, alert = candidates[0]
                    matched_alerts.add(index); tp += 1; s_tp += 1
                    if label["cause"] == "sustained_increase":
                        delay = (date.fromisoformat(alert["start_date"]) - (start + timedelta(days=label["start"]))).days
                        delays.append(max(0, delay))
                    attribution_total += 1; s_attr_total += 1
                    if alert["contributors"] and alert["contributors"][0]["service"] == label["service"]:
                        attribution_correct += 1; s_attr += 1
                else:
                    fn += 1; s_fn += 1
            false_count = sum(1 for i in range(len(alerts)) if i not in matched_alerts)
            fp += false_count; s_fp += false_count
        n_days = len(SEEDS) * N_DAYS
        by_scenario[scenario] = {
            "scenarios": len(SEEDS), "true_positives": s_tp, "false_positives": s_fp,
            "false_negatives": s_fn,
            "false_alerts_per_30_days": round(s_fp / n_days * 30, 3),
            "attribution_top1_accuracy": round(s_attr / s_attr_total, 4) if s_attr_total else None,
        }
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {
        "alert_limit_per_scenario": 20,
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "false_alerts_per_30_days": round(fp / (len(SEEDS) * len(SCENARIOS) * N_DAYS) * 30, 3),
        "sustained_detection_delay_days_median": sorted(delays)[len(delays) // 2] if delays else None,
        "attribution_top1_accuracy": round(attribution_correct / attribution_total, 4) if attribution_total else None,
        "by_scenario": by_scenario,
    }


def evaluate_previous_day():
    tp = fp = fn = 0
    for scenario in SCENARIOS:
        for seed in SEEDS:
            rows, labels = make_scenario(seed, scenario)
            totals = {}
            for row in rows: totals[row.day] = totals.get(row.day, 0.0) + float(row.cost)
            days = sorted(totals)
            alarms = [i for i in range(1, len(days)) if totals[days[i]]-totals[days[i-1]] >= 5 and totals[days[i]] >= totals[days[i-1]] * 1.35]
            alarms = sorted(alarms, key=lambda i: totals[days[i]] - totals[days[i-1]], reverse=True)[:20]
            start = days[0]
            matched = set()
            for label in labels:
                label_days = set(range(label["start"], label["end"] + 1))
                found = [i for i, offset in enumerate(alarms) if offset in label_days]
                if found: tp += 1; matched.update(found)
                else: fn += 1
            fp += len(alarms) - len(matched)
    return {"alert_limit_per_scenario": 20, "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": round(tp/(tp+fp),4) if tp+fp else 0,
            "recall": round(tp/(tp+fn),4) if tp+fn else 0,
            "false_alerts_per_30_days": round(fp/(len(SEEDS)*len(SCENARIOS)*N_DAYS)*30,3)}


def main():
    payload = {
        "title": "Cloud Cost Anomaly Explainer synthetic evaluation",
        "dataset": {"type": "synthetic", "seed_range": [SEEDS.start, SEEDS.stop - 1], "scenarios_per_type": len(SEEDS), "days_per_scenario": N_DAYS,
                    "scenario_types": list(SCENARIOS), "injected_events": "One known spike or sustained increase per matching scenario; normal and noisy scenarios have no injected events."},
        "split": "Held-out generated scenarios. Reserved seed range 3100-3139; no fit or threshold selection is performed by this script.",
        "thresholds": {"minimum_absolute_delta_usd": 5, "minimum_relative_delta": 0.35, "mad_multiplier": 3.5, "sustained_days": 3, "alert_limit": 20},
        "detector": evaluate_detector(),
        "previous_day_comparator": evaluate_previous_day(),
        "limitations": ["All data is synthetic and generated from a small set of simple service patterns.", "This measures event detection in these scenarios, not expected performance on real billing exports.", "Scenarios share the same generation family; seed holdout does not establish generalization across providers or billing schemas."],
    }
    out = ROOT / "evaluation" / "results.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report = ["# Synthetic evaluation report", "", "This report is generated by `python -m evaluation.run`. Data is synthetic; results do not establish performance on customer bills.", "",
              f"Held-out seeds: {SEEDS.start}–{SEEDS.stop-1}; {len(SEEDS)} scenarios per type; {N_DAYS} simulated days each.", "",
              "| Metric | History-only detector | Previous-day comparator |", "|---|---:|---:|"]
    for key, label in [("precision", "Precision"), ("recall", "Recall"), ("false_alerts_per_30_days", "False alerts per 30 simulated days")]:
        report.append(f"| {label} | {payload['detector'][key]} | {payload['previous_day_comparator'][key]} |")
    report += [f"| Median sustained detection delay (days) | {payload['detector']['sustained_detection_delay_days_median']} | Not measured |",
               f"| Top contributor matches planted cause | {payload['detector']['attribution_top1_accuracy']} | Not measured |", "", "## By scenario", "",
               "| Scenario | TP | FP | FN | False alerts / 30 days | Top attribution accuracy |", "|---|---:|---:|---:|---:|---:|"]
    for name, result in payload["detector"]["by_scenario"].items():
        report.append(f"| {name} | {result['true_positives']} | {result['false_positives']} | {result['false_negatives']} | {result['false_alerts_per_30_days']} | {result['attribution_top1_accuracy']} |")
    report += ["", "## Limitations", ""] + [f"- {item}" for item in payload["limitations"]]
    (ROOT / "evaluation" / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"results": str(out), "report": str(ROOT / 'evaluation' / 'REPORT.md')}, indent=2))


if __name__ == "__main__":
    main()
