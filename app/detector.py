"""Deterministic, history-only cost baselines and evidence-backed alerts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from .csv_data import BillingRow

MIN_ABSOLUTE_DELTA = Decimal("5.00")
MIN_RELATIVE_DELTA = Decimal("0.35")
MAD_MULTIPLIER = Decimal("3.5")
MIN_HISTORY = 4
SUSTAINED_DAYS = 3
MAX_ALERTS = 20


def money(value: Decimal | float | int) -> float:
    return round(float(value), 4)


def analyze(rows: list[BillingRow], source_name: str = "Uploaded CSV") -> dict:
    daily: dict[date, Decimal] = defaultdict(Decimal)
    by_service: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    dimensions: dict[str, dict[str, dict[date, Decimal]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    currency = rows[0].currency
    for row in rows:
        daily[row.day] += row.cost
        by_service[row.service][row.day] += row.cost
        for dimension in ("sku", "project", "region", "team"):
            value = getattr(row, dimension)
            if value:
                dimensions[dimension][value][row.day] += row.cost
    days = sorted(daily)
    if len(days) < 5:
        raise ValueError("At least five distinct dates are needed to establish a useful baseline.")

    expected: dict[date, Decimal] = {}
    scores: dict[date, float] = {}
    thresholds: dict[date, Decimal] = {}
    methods: dict[date, str] = {}
    candidates: list[date] = []
    for idx, day in enumerate(days):
        history_days = days[:idx]
        weekday_history = [d for d in history_days if d.weekday() == day.weekday()][-8:]
        if len(weekday_history) >= MIN_HISTORY:
            ref_days = weekday_history
            method = "same weekday, up to 8 prior observations"
        else:
            ref_days = history_days[-14:]
            method = "prior 14 observed days (weekday history fallback)"
        if len(ref_days) < MIN_HISTORY:
            expected[day] = daily[day]
            scores[day] = 0.0
            thresholds[day] = MIN_ABSOLUTE_DELTA
            methods[day] = "insufficient history; alerting disabled"
            continue
        values = [daily[d] for d in ref_days]
        center = median(values)
        deviations = [abs(v - center) for v in values]
        mad = median(deviations)
        # Scale MAD to a normal-equivalent sigma; the absolute floor handles stable series.
        robust_spread = Decimal(str(mad)) * Decimal("1.4826")
        threshold = max(MIN_ABSOLUTE_DELTA, Decimal(str(center)) * MIN_RELATIVE_DELTA, robust_spread * MAD_MULTIPLIER)
        delta = daily[day] - Decimal(str(center))
        expected[day] = Decimal(str(center))
        thresholds[day] = threshold
        methods[day] = method
        scores[day] = money(delta / max(robust_spread, Decimal("0.01")))
        if delta >= threshold:
            candidates.append(day)

    candidate_set = set(candidates)
    ranges: list[tuple[list[date], str]] = []
    i = 0
    while i < len(days):
        if days[i] not in candidate_set:
            i += 1
            continue
        run = [days[i]]
        j = i + 1
        while j < len(days) and days[j] in candidate_set and days[j] - days[j - 1] == timedelta(days=1):
            run.append(days[j])
            j += 1
        ranges.append((run, "sustained_increase" if len(run) >= SUSTAINED_DAYS else "spike"))
        i = j

    alerts = []
    for window, kind in ranges:
        first, last = window[0], window[-1]
        observed = sum((daily[d] for d in window), Decimal(0))
        baseline = sum((expected[d] for d in window), Decimal(0))
        delta = observed - baseline
        service_delta: dict[str, Decimal] = defaultdict(Decimal)
        for day in window:
            hist = [d for d in days if d < day and d.weekday() == day.weekday()][-8:]
            if len(hist) < 2:
                hist = [d for d in days if d < day][-14:]
            for service, series in by_service.items():
                actual = series.get(day, Decimal(0))
                base_values = [series.get(d, Decimal(0)) for d in hist]
                service_delta[service] += actual - (Decimal(str(median(base_values))) if base_values else Decimal(0))
        contributors = sorted(
            ({"service": name, "delta": money(value)} for name, value in service_delta.items() if value > 0),
            key=lambda item: item["delta"],
            reverse=True,
        )
        top = contributors[:5]
        attributed = sum((Decimal(str(c["delta"])) for c in top), Decimal(0))
        dimension_contributors = {}
        for dimension, values in dimensions.items():
            changes: dict[str, Decimal] = defaultdict(Decimal)
            for day in window:
                hist = [d for d in days if d < day and d.weekday() == day.weekday()][-8:]
                if len(hist) < MIN_HISTORY:
                    hist = [d for d in days if d < day][-14:]
                for name, series in values.items():
                    historic = [series.get(d, Decimal(0)) for d in hist]
                    center = Decimal(str(median(historic))) if historic else Decimal(0)
                    changes[name] += series.get(day, Decimal(0)) - center
            dimension_contributors[dimension] = sorted(
                ({"name": name, "delta": money(value)} for name, value in changes.items() if value > 0),
                key=lambda item: item["delta"], reverse=True,
            )[:3]
        alerts.append(
            {
                "id": f"{first.isoformat()}-{kind}",
                "type": kind,
                "start_date": first.isoformat(),
                "end_date": last.isoformat(),
                "observed": money(observed),
                "expected": money(baseline),
                "delta": money(delta),
                "score": max(scores[d] for d in window),
                "threshold": money(sum((thresholds[d] for d in window), Decimal(0))),
                "baseline_method": methods[first],
                "contributors": top,
                "dimension_contributors": dimension_contributors,
                "unexplained_residual": money(delta - attributed),
                "evidence": [
                    f"Observed {currency} {money(observed):,.2f} against expected {currency} {money(baseline):,.2f}.",
                    f"Increase of {currency} {money(delta):,.2f}; threshold for the window was {currency} {money(sum((thresholds[d] for d in window), Decimal(0))):,.2f}.",
                    f"Baseline uses {methods[first]} and only data dated before each alert day.",
                ],
            }
        )

    chart = [
        {"date": d.isoformat(), "actual": money(daily[d]), "expected": money(expected[d]), "score": scores[d]}
        for d in days
    ]
    service_totals: dict[str, Decimal] = defaultdict(Decimal)
    dimension_totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for service, series in by_service.items():
        service_totals[service] = sum(series.values(), Decimal(0))
    for row in rows:
        for dimension in ("sku", "project", "region", "team"):
            value = getattr(row, dimension)
            if value:
                dimension_totals[dimension][value] += row.cost
    breakdown = sorted(
        ({"service": name, "total": money(total)} for name, total in service_totals.items()),
        key=lambda item: item["total"],
        reverse=True,
    )[:20]
    return {
        "source": source_name,
        "synthetic": False,
        "currency": currency,
        "date_range": {"start": days[0].isoformat(), "end": days[-1].isoformat()},
        "row_count": len(rows),
        "daily": chart,
        "service_breakdown": breakdown,
        "dimension_breakdown": {
            dimension: sorted(
                ({"name": name, "total": money(total)} for name, total in values.items()),
                key=lambda item: item["total"],
                reverse=True,
            )[:20]
            for dimension, values in dimension_totals.items()
        },
        "alerts": alerts[:MAX_ALERTS],
        "thresholds": {
            "minimum_absolute_delta": money(MIN_ABSOLUTE_DELTA),
            "minimum_relative_delta": money(MIN_RELATIVE_DELTA),
            "mad_multiplier": money(MAD_MULTIPLIER),
            "minimum_history_observations": MIN_HISTORY,
            "sustained_days": SUSTAINED_DAYS,
        },
        "limitations": [
            "The detector analyzes daily totals and uses prior observations only; it does not model budgets, billing credits, or usage drivers.",
            "Sparse, irregular, or newly introduced services can have weak baselines. Review the shown evidence before acting.",
            "Attribution is a service-level estimate against historical medians; the residual makes incomplete attribution visible.",
        ],
    }
