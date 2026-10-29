"""Strict, bounded parsing for the canonical billing CSV format."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 100_000
REQUIRED = {"date", "service", "cost"}
OPTIONAL = {"sku", "project", "region", "team", "currency"}
ALLOWED = REQUIRED | OPTIONAL


class CsvInputError(ValueError):
    """A safe, user-facing CSV validation error."""


@dataclass(frozen=True)
class BillingRow:
    day: date
    service: str
    sku: str
    project: str
    region: str
    team: str
    cost: Decimal
    currency: str


def parse_billing_csv(raw: bytes) -> list[BillingRow]:
    if not raw:
        raise CsvInputError("The CSV file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise CsvInputError("The file is larger than the 5 MiB upload limit.")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvInputError("The file must be UTF-8 encoded.") from exc
    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        headers = [str(h).strip().lower() for h in (reader.fieldnames or [])]
        if not headers or any(not h for h in headers):
            raise CsvInputError("Add a header row with date, service, and cost columns.")
        if len(headers) != len(set(headers)):
            raise CsvInputError("Column names must be unique.")
        missing = REQUIRED - set(headers)
        if missing:
            raise CsvInputError("Missing required columns: " + ", ".join(sorted(missing)) + ".")
        unknown = set(headers) - ALLOWED
        if unknown:
            raise CsvInputError("Unsupported columns: " + ", ".join(sorted(unknown)) + ".")
        reader.fieldnames = headers
        rows: list[BillingRow] = []
        currencies: set[str] = set()
        for line_no, item in enumerate(reader, start=2):
            if line_no > MAX_ROWS + 1:
                raise CsvInputError(f"The file has more than {MAX_ROWS:,} data rows.")
            if None in item:
                raise CsvInputError(f"Row {line_no} has more values than the header.")
            values = {k: (v or "").strip() for k, v in item.items()}
            if not any(values.values()):
                continue
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["date"]):
                    raise ValueError
                day = date.fromisoformat(values["date"])
            except (ValueError, TypeError) as exc:
                raise CsvInputError(f"Row {line_no}: date must use YYYY-MM-DD format.") from exc
            service = values["service"]
            if not service or len(service) > 120:
                raise CsvInputError(f"Row {line_no}: service is required and must be at most 120 characters.")
            try:
                cost = Decimal(values["cost"])
            except (InvalidOperation, KeyError) as exc:
                raise CsvInputError(f"Row {line_no}: cost must be a non-negative number.") from exc
            if not cost.is_finite() or cost < 0 or cost.adjusted() > 12:
                raise CsvInputError(f"Row {line_no}: cost must be a finite, non-negative amount.")
            currency = values.get("currency", "USD").upper() or "USD"
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise CsvInputError(f"Row {line_no}: currency must be a three-letter code.")
            currencies.add(currency)
            rows.append(
                BillingRow(
                    day=day,
                    service=service,
                    sku=values.get("sku", "")[:120],
                    project=values.get("project", "")[:120],
                    region=values.get("region", "")[:120],
                    team=values.get("team", "")[:120],
                    cost=cost,
                    currency=currency,
                )
            )
        if not rows:
            raise CsvInputError("The CSV has no usable billing rows.")
        if len(currencies) > 1:
            raise CsvInputError("Use one currency per upload so cost changes can be compared safely.")
        return rows
    except csv.Error as exc:
        raise CsvInputError("The CSV could not be parsed. Check its quoting and delimiter.") from exc


def summarize_dimensions(rows: list[BillingRow]) -> dict[str, list[dict[str, str]]]:
    dims: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for field in ("project", "region", "team", "sku"):
            value = getattr(row, field)
            if value:
                dims[field].add(value)
    return {key: [{"name": v} for v in sorted(values)] for key, values in dims.items()}
