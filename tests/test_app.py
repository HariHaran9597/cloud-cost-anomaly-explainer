from __future__ import annotations

import json
from collections import deque
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import investigator, main
from app.csv_data import BillingRow, CsvInputError, parse_billing_csv
from app.detector import analyze

client = TestClient(main.app)


def csv_bytes(days: int = 5) -> bytes:
    start = date(2026, 1, 1)
    lines = ["date,service,cost,currency"]
    for offset in range(days):
        lines.append(f"{start + timedelta(days=offset)},Compute,10.25,USD")
    return ("\n".join(lines) + "\n").encode()


def test_csv_parser_accepts_utf8_bom_and_canonical_optional_fields():
    raw = b"\xef\xbb\xbfdate,service,cost,team\n2026-01-01,Compute,12.50,platform\n"
    row = parse_billing_csv(raw)[0]
    assert row.day == date(2026, 1, 1)
    assert row.cost == Decimal("12.50")
    assert row.team == "platform"
    assert row.currency == "USD"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "empty"),
        (b"date,service,cost\n2026-1-1,Compute,1\n", "YYYY-MM-DD"),
        (b"date,service,cost\n2026-01-01,Compute,-1\n", "non-negative"),
        (b"date,service,cost\n2026-01-01,Compute,NaN\n", "finite"),
        (b"date,service,cost,wat\n2026-01-01,Compute,1,x\n", "Unsupported columns"),
        (b"date,date,service,cost\n2026-01-01,2026-01-01,Compute,1\n", "unique"),
        (b"date,service,cost,currency\n2026-01-01,A,1,USD\n2026-01-02,B,1,EUR\n", "one currency"),
    ],
)
def test_csv_parser_rejects_invalid_inputs(raw: bytes, message: str):
    with pytest.raises(CsvInputError, match=message):
        parse_billing_csv(raw)


def test_csv_parser_rejects_oversized_body():
    with pytest.raises(CsvInputError, match="4 MiB"):
        parse_billing_csv(b"x" * (main.MAX_UPLOAD_BYTES + 1))


def test_sample_is_repeatable_and_has_two_planted_alerts():
    response = client.get("/api/sample")
    assert response.status_code == 200
    payload = response.json()
    assert payload["synthetic"] is True
    assert len(payload["alerts"]) == 2
    assert {item["type"] for item in payload["alerts"]} == {"spike", "sustained_increase"}
    assert client.get("/api/sample").json() == payload


def test_upload_validates_and_analyzes_in_memory():
    response = client.post("/api/analyze", content=csv_bytes(), headers={"content-type": "text/csv", "x-file-name": "cost.csv"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "cost.csv"
    assert payload["row_count"] == 5
    assert payload["currency"] == "USD"


def test_upload_rejects_unsupported_media_type():
    response = client.post("/api/analyze", content=csv_bytes(), headers={"content-type": "text/plain"})
    assert response.status_code == 415


def test_upload_rejects_invalid_csv_with_safe_detail():
    response = client.post("/api/analyze", content=b"not,a,billing,csv\n", headers={"content-type": "text/csv"})
    assert response.status_code == 400
    assert "Missing required columns" in response.json()["detail"]


def test_upload_enforces_streaming_body_limit():
    body = b"x" * (main.MAX_UPLOAD_BYTES + 1)
    response = client.post("/api/analyze", content=body, headers={"content-type": "text/csv"})
    assert response.status_code == 413


def test_health_readiness_security_headers_and_report_download(monkeypatch: pytest.MonkeyPatch):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    response = client.get("/api/report")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.json()["synthetic"] is True
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"]
    monkeypatch.setattr(main, "SAMPLE", main.SAMPLE.with_name("missing-sample.csv"))
    assert client.get("/readyz").status_code == 503


def test_frontend_uses_self_hosted_assets_without_inline_styles():
    response = client.get("/")
    assert response.status_code == 200
    assert '/static/app.js' in response.text
    assert "style=" not in response.text
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]


def test_investigator_is_disabled_without_configuration(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INVESTIGATOR_API_KEY", raising=False)
    monkeypatch.delenv("INVESTIGATOR_MODEL", raising=False)
    assert investigator.configuration() is None
    assert client.get("/api/investigator/status").json()["enabled"] is False
    response = client.post("/api/investigator", content=csv_bytes(), headers={"content-type": "text/csv"})
    assert response.status_code == 503


def test_investigator_rejects_cross_origin_requests(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "configuration", lambda: ("https://example.test/chat", "secret", "model"))
    response = client.post(
        "/api/investigator",
        content=csv_bytes(),
        headers={"content-type": "text/csv", "origin": "https://attacker.example", "host": "testserver"},
    )
    assert response.status_code == 403


def test_investigator_rate_limit_is_bounded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(investigator, "_calls", {})
    monkeypatch.setattr(investigator, "_global_calls", deque())
    assert all(investigator.allow_call("client-a") for _ in range(3))
    assert not investigator.allow_call("client-a")
    assert investigator.allow_call("client-b")


def test_investigator_has_a_per_process_cap(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(investigator, "_calls", {})
    monkeypatch.setattr(investigator, "_global_calls", deque())
    monkeypatch.setattr(investigator, "MAX_GLOBAL_CALLS_PER_MINUTE", 2)
    assert investigator.allow_call("client-a")
    assert investigator.allow_call("client-b")
    assert not investigator.allow_call("client-c")


@pytest.mark.parametrize(
    "summary",
    [
        "No alert crossed the configured threshold [E1]. The analysis used five dates.",
        "The alert increased by USD 999.00 [E1]. No other alert crossed the configured threshold [E1].",
    ],
)
def test_investigator_rejects_uncited_or_unsupported_claims(monkeypatch: pytest.MonkeyPatch, summary: str):
    rows = [BillingRow(date(2026, 1, day), "Compute", "", "", "", "", Decimal("10"), "USD") for day in range(1, 6)]
    report = analyze(rows)
    monkeypatch.setattr(investigator, "configuration", lambda: ("https://example.test/chat", "secret", "model"))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            result = {"choices": [{"message": {"content": json.dumps({"summary": summary, "citations": ["E1"]})}}]}
            return json.dumps(result).encode()

    monkeypatch.setattr(investigator, "urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(investigator.InvestigatorError):
        investigator.investigate(report)


def test_investigator_accepts_evidence_cited_summary(monkeypatch: pytest.MonkeyPatch):
    rows = [BillingRow(date(2026, 1, day), "Compute", "", "", "", "", Decimal("10"), "USD") for day in range(1, 6)]
    report = analyze(rows)
    monkeypatch.setattr(investigator, "configuration", lambda: ("https://example.test/chat", "secret", "model"))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            generated = {"summary": "No alert crossed the configured threshold [E1]. The analysis covers observed dates [E1].", "citations": ["E1"]}
            return json.dumps({"choices": [{"message": {"content": json.dumps(generated)}}]}).encode()

    monkeypatch.setattr(investigator, "urlopen", lambda *_args, **_kwargs: Response())
    result = investigator.investigate(report)
    assert result["citations"] == ["E1"]
    assert "No alert crossed" in result["summary"]
