from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .csv_data import MAX_DIMENSION_VALUES, MAX_DISTINCT_DATES, MAX_ROWS, MAX_SERVICES, MAX_UPLOAD_BYTES, CsvInputError, parse_billing_csv
from .detector import analyze
from .investigator import InvestigatorError, allow_call, configuration, investigate

SAMPLE = Path(__file__).resolve().parent / "data" / "sample_billing.csv"
STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="Cloud Cost Anomaly Explainer", version="0.1.0", docs_url=None, redoc_url=None)


async def read_bounded_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/csv", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Send the file as text/csv or application/octet-stream.")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The file is larger than the 5 MiB upload limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    effective_scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    if effective_scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    if not SAMPLE.is_file():
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}


@app.get("/api/sample")
async def sample():
    rows = parse_billing_csv(SAMPLE.read_bytes())
    result = analyze(rows, "Bundled synthetic sample")
    result["synthetic"] = True
    result["synthetic_notice"] = "Synthetic billing data with planted anomalies; it does not represent customer savings or real cloud usage."
    result["synthetic_labels"] = json.loads((SAMPLE.parent / "sample_labels.json").read_text(encoding="utf-8"))
    return result


@app.get("/api/sample.csv")
async def sample_csv():
    return FileResponse(SAMPLE, media_type="text/csv", filename="synthetic_billing_sample.csv")


@app.get("/api/sample/labels")
async def sample_labels():
    return json.loads((SAMPLE.parent / "sample_labels.json").read_text(encoding="utf-8"))


@app.post("/api/analyze")
async def analyze_upload(request: Request):
    raw = await read_bounded_body(request)
    try:
        rows = await run_in_threadpool(parse_billing_csv, raw)
        filename = Path(request.headers.get("x-file-name", "Uploaded CSV")).name[:120]
        return await run_in_threadpool(analyze, rows, filename)
    except CsvInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/report")
async def report():
    rows = parse_billing_csv(SAMPLE.read_bytes())
    result = analyze(rows, "Bundled synthetic sample")
    result["synthetic"] = True
    result["synthetic_notice"] = "Synthetic data only; no real savings are claimed."
    return JSONResponse(
        result,
        headers={"Content-Disposition": 'attachment; filename="cloud-cost-investigation.json"'},
    )


@app.get("/api/schema")
async def schema():
    return {
        "columns": [
            {"name": "date", "required": True, "format": "YYYY-MM-DD"},
            {"name": "service", "required": True},
            {"name": "sku", "required": False},
            {"name": "project", "required": False},
            {"name": "region", "required": False},
            {"name": "team", "required": False},
            {"name": "cost", "required": True, "format": "non-negative decimal"},
            {"name": "currency", "required": False, "default": "USD", "format": "one ISO-like 3-letter code per file"},
        ],
        "limits": {
            "max_file_bytes": MAX_UPLOAD_BYTES,
            "max_rows": MAX_ROWS,
            "max_distinct_dates": MAX_DISTINCT_DATES,
            "max_services": MAX_SERVICES,
            "max_values_per_optional_dimension": MAX_DIMENSION_VALUES,
        },
    }


@app.get("/api/investigator/status")
async def investigator_status():
    return {"enabled": configuration() is not None, "requires_explicit_upload": True}


@app.post("/api/investigator")
async def investigate_upload(request: Request):
    if configuration() is None:
        raise HTTPException(status_code=503, detail="The optional investigator is not configured on this server.")
    origin = request.headers.get("origin")
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    if not origin or urlparse(origin).netloc != request.headers.get("host") or urlparse(origin).scheme != forwarded_proto:
        raise HTTPException(status_code=403, detail="Cross-origin investigator requests are not accepted.")
    if not allow_call(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="The investigator call limit was reached. Try again in a minute.")
    raw = await read_bounded_body(request)
    try:
        rows = await run_in_threadpool(parse_billing_csv, raw)
        result = await run_in_threadpool(analyze, rows, "Uploaded billing CSV")
        return await asyncio.to_thread(investigate, result)
    except CsvInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvestigatorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
