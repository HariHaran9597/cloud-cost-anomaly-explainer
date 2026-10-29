"""Seeded synthetic billing data for the public demo and evaluation."""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path


def generate(seed: int = 20261029, days: int = 84) -> tuple[list[dict[str, str]], list[str]]:
    rng = random.Random(seed)
    start = date(2026, 1, 1)
    services = {"Compute Engine": 34.0, "Cloud Storage": 9.0, "Managed Database": 18.0, "Network Egress": 6.0}
    rows: list[dict[str, str]] = []
    labels = [
        {"start_date": "2026-02-15", "end_date": "2026-02-15", "type": "spike", "service": "Network Egress", "added_cost_per_day": 24.0},
        {"start_date": "2026-03-05", "end_date": "2026-03-08", "type": "sustained_increase", "service": "Managed Database", "added_cost_per_day": 30.0},
    ]
    for offset in range(days):
        day = start + timedelta(days=offset)
        for service, base in services.items():
            weekend = 0.86 if day.weekday() >= 5 and service == "Compute Engine" else 1.0
            noise = rng.uniform(-0.07, 0.07)
            cost = base * weekend * (1 + noise)
            if day.isoformat() == "2026-02-15" and service == "Network Egress":
                cost += 24.0
            if date.fromisoformat("2026-03-05") <= day <= date.fromisoformat("2026-03-08") and service == "Managed Database":
                cost += 30.0
            rows.append(
                {
                    "date": day.isoformat(),
                    "service": service,
                    "sku": f"{service} usage",
                    "project": "demo-project",
                    "region": "us-central1",
                    "team": "platform",
                    "cost": f"{cost:.2f}",
                    "currency": "USD",
                }
            )
    return rows, labels


def write_sample(path: Path) -> None:
    rows, labels = generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (path.parent / "sample_labels.json").write_text(json.dumps({"synthetic": True, "seed": 20261029, "planted_events": labels}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_sample(Path(__file__).resolve().parent / "data" / "sample_billing.csv")
