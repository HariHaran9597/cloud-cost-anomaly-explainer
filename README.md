# Cloud Cost Anomaly Explainer

Answer **“what changed in our cloud bill?”** from a normalized billing CSV. The application builds daily baselines from prior observations, flags large spikes and sustained increases, and shows service-level contributors and unexplained residuals.

> **Release status: implementation in progress.** The local app, detector, synthetic data, and evaluation workflow are being built. No public deployment, GitHub push, or live URL has been verified. The bundled sample is synthetic and does not represent real usage or savings.

## Run locally

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m app.synthetic
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. The bundled sample works without an account or API key. Uploaded data is held only while the request is processed; raw billing rows are not logged or written to disk.

## CSV contract

```csv
date,service,sku,project,region,team,cost,currency
2026-01-01,Compute Engine,Compute instance,demo,us-central1,platform,12.50,USD
```

Required columns: `date`, `service`, `cost`. Optional columns: `sku`, `project`, `region`, `team`, `currency` (defaults to USD). Use UTF-8, ISO dates (`YYYY-MM-DD`), non-negative decimal costs, and one currency code per file. Unknown or duplicate columns are rejected. Upload limits: 5 MiB, 100,000 rows, 730 distinct dates, 500 services, and 2,000 values in each optional dimension. At least five distinct dates are needed. Download the canonical schema at `/api/schema` and sample at `/api/sample.csv`; planted sample labels are available at `/api/sample/labels`.

## Detection and interpretation

- Each date uses only earlier rows to build its baseline.
- The preferred baseline is the median of up to eight prior observations on the same weekday. During warm-up, the detector falls back to prior observed days.
- A candidate increase must clear all applicable floors: 5 units of the file currency as the minimum absolute change, 35% of expected cost, and 3.5 scaled median absolute deviations. These are defaults, not universal FinOps thresholds.
- Three or more consecutive candidate dates are grouped as a sustained increase; shorter runs are spikes.
- Service contributors compare each service with its own historical median. The report shows an unexplained residual because service attribution may not reconcile perfectly.
- Daily series use observed dates in the CSV. A missing date is treated as missing data, not as zero spend.

The detector does not account for budgets, credits, commitments, usage meters, billing adjustments, or provider-specific export semantics. Sparse histories and new services weaken the baseline. The app does not connect to cloud accounts, change infrastructure, or claim savings.

## Architecture

- FastAPI API and static single-page interface in one container.
- Standard-library CSV parsing and deterministic calculations; no database, worker, or required LLM.
- `GET /healthz` is a process health check; `GET /readyz` also checks that the bundled sample exists.
- `POST /api/analyze` accepts a bounded CSV upload; `GET /api/sample` returns the synthetic demo.
- Security headers are set by middleware. Browser rendering uses DOM text APIs for user-controlled labels; only escaped chart values enter SVG markup.

## Synthetic evaluation

Reproduce the held-out synthetic evaluation:

```powershell
python -m evaluation.run
```

The script writes `evaluation/results.json` and `evaluation/REPORT.md`, comparing the history-only detector with a previous-day percentage-change comparator. The seed range, scenarios, fixed thresholds, alert cap, metrics, and limitations are recorded in the outputs. The results describe only generated data and should not be presented as real-bill performance.

## Container

```powershell
docker build -t cloud-cost-anomaly-explainer .
docker run --rm -p 8000:8000 cloud-cost-anomaly-explainer
```

For deployment, use one low-capacity request-based service, set a budget alert, and verify current provider pricing before creating cloud resources. No deployment is included in this local build.

## Optional AI investigator

The core workflow does not call an LLM. To enable the optional investigator, configure `INVESTIGATOR_API_KEY` and `INVESTIGATOR_MODEL` as server environment variables. The `INVESTIGATOR_CHAT_COMPLETIONS_URL` setting can point to an HTTPS OpenAI-compatible chat completions endpoint; it defaults to `https://api.openai.com/v1/chat/completions`. The investigator is hidden when no key and model are configured. On an explicit click, the selected CSV is uploaded again; only computed aggregate figures and service names go to the provider. Calls are limited to three per minute per client address, time out after eight seconds, and cap the response size and output tokens. Generated summaries must cite the evidence IDs and numeric claims must match cited evidence. Never put provider keys in browser configuration or logs.

## Current synthetic evaluation

The reserved generated seed set currently measures **1.0 precision**, **1.0 recall**, **0.0 false alerts per 30 simulated days**, **0 day median sustained detection delay**, and **1.0 top-contributor accuracy** for the history-only detector. The previous-day comparator measured 0.9412 precision and 1.0 recall on the same scenarios. These results come from 40 seeds per scenario type across 90 simulated days, with one deliberately strong spike or sustained increase in labeled scenarios. They measure only this generator family; they do not establish performance on real billing data. Re-run `python -m evaluation.run` to reproduce the checked-in report.

## Release checklist

- [x] Canonical CSV contract, validation, size and row limits
- [x] Seeded synthetic sample with known injected changes
- [x] History-only daily baseline, spike and sustained classifications
- [x] Top service attribution and residual reporting
- [x] Sample workflow, CSV upload, chart, evidence, and JSON download
- [x] Repeatable synthetic evaluation harness and report generation
- [x] Health/readiness routes, container, and CI workflow
- [x] Optional bounded read-only investigator with explicit user action and evidence citations
- [ ] Run release checks and review measured evaluation output
- [ ] Publish repository and deploy public demo
- [ ] Verify live URL in a clean browser session

V1 is not shipped until the checked items above and the public URL, source repository, and deployed version agree.
