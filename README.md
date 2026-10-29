# Cloud Cost Anomaly Explainer

[![CI](https://github.com/HariHaran9597/cloud-cost-anomaly-explainer/actions/workflows/check.yml/badge.svg?branch=main)](https://github.com/HariHaran9597/cloud-cost-anomaly-explainer/actions/workflows/check.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**A CSV-first investigation tool for answering: _what changed in our cloud bill?_** Upload a normalized billing CSV or load the bundled synthetic sample to compare daily spend with a history-only baseline, inspect anomalies and contributors, and download an evidence report.

> **Release status:** source repository and CI are ready. A hosted public demo has not been deployed or verified. This project is a focused investigation demo, not a replacement for a FinOps platform and not evidence of customer savings.

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Billing CSV format](#billing-csv-format)
- [How detection works](#how-detection-works)
- [Evaluation](#evaluation)
- [External sample smoke checks](#external-sample-smoke-checks)
- [Why no trained ML model](#why-no-trained-ml-model)
- [Architecture and privacy](#architecture-and-privacy)
- [Optional AI investigator](#optional-ai-investigator)
- [Deployment recommendation](#deployment-recommendation)
- [Limitations and next steps](#limitations-and-next-steps)
- [License](#license)

## What it does

- Loads a clearly labeled synthetic sample or analyzes a user-provided CSV.
- Aggregates daily spend and shows actual cost against a baseline built from earlier observations.
- Flags spike and sustained-increase windows, with the measured amount, expected amount, threshold, score, and date range.
- Ranks service and optional dimension changes; shows a residual when the service estimates do not explain the total change.
- Displays a chart, alert evidence, thresholds, limitations, and a downloadable JSON report.
- Optionally asks a configured LLM to summarize computed evidence. Detection still works without an API key.

The application does not connect to cloud accounts, alter resources, forecast a budget, identify a causal root cause, or claim money saved.

## Quick start

Requires Python 3.11 or later.

**Windows PowerShell**

```powershell
python -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install -e .
uvicorn app.main:app --reload
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> and choose **Load synthetic sample**. No account, cloud credentials, database, or LLM key is needed for the main workflow.

To run the repeatable evaluation and test suite:

```bash
python -m pip install -e '.[dev]'
python -m evaluation.run
pytest -q
```

## Billing CSV format

The upload contract is deliberately small and provider-neutral:

```csv
date,service,sku,project,region,team,cost,currency
2026-01-01,Compute Engine,Compute instance,demo,us-central1,platform,12.50,USD
```

| Column | Required | Meaning |
|---|---:|---|
| `date` | Yes | Usage date in `YYYY-MM-DD` format |
| `service` | Yes | Service or product name used for grouping |
| `cost` | Yes | Non-negative decimal charge |
| `sku` | No | Product or usage SKU |
| `project` | No | Project, subscription, or account grouping |
| `region` | No | Resource region |
| `team` | No | Team or owner grouping |
| `currency` | No | One three-letter currency code per file; defaults to `USD` |

The app rejects unknown or duplicate columns, malformed dates and amounts, mixed currencies, and files outside its bounds. Limits are 5 MiB, 100,000 rows, 730 observed dates, 500 services, and 2,000 distinct values per optional dimension. At least five distinct dates are required. The canonical schema is available at `GET /api/schema`, the bundled CSV at `GET /api/sample.csv`, and planted sample events at `GET /api/sample/labels`.

**Provider exports are not imported directly.** An AWS, Azure, or Google Cloud export must first be mapped to this normalized contract. Provider-specific semantics such as credits, adjustments, amortization, and commitment charges can change the interpretation of a cost column.

## How detection works

The detector is deterministic statistical logic; it does not train a model.

1. Costs are summed by observed date. Missing dates are treated as missing data, not as zero spend.
2. For each date, the preferred baseline is the median of up to eight earlier observations on the same weekday. During warm-up, it falls back to earlier observed days. The current and future rows are never used to set that date's baseline.
3. A positive change is a candidate only when it clears the configured absolute, relative, and scaled median-absolute-deviation thresholds.
4. Runs of at least three consecutive calendar days are labeled sustained increases; shorter runs are labeled spikes.
5. Service and dimension attribution compares each group with its own historical median. It is an estimate, not causal root-cause analysis; the residual makes incomplete reconciliation visible.

Defaults are a 5-unit absolute floor in the file currency, a 35% relative floor, a 3.5 scaled-MAD floor, four prior observations to enable detection, and three consecutive candidate days for a sustained increase. These defaults are not universal FinOps thresholds. The app exposes the settings and evidence with each result.

## Evaluation

The checked-in evaluation uses generated scenarios, not customer bills. It runs 40 seeds for each of four scenario types (normal, spike, sustained increase, and noisy), with 90 simulated days per scenario. The detector and previous-day percentage-change comparator use the same held-out scenarios.

| Metric | History-only detector | Previous-day comparator |
|---|---:|---:|
| Precision | 1.0000 | 0.9412 |
| Recall | 1.0000 | 1.0000 |
| False alerts per 30 simulated days | 0.000 | 0.010 |
| Median sustained detection delay | 0 days | Not measured |
| Top-contributor accuracy | 1.0000 | Not measured |

These results describe performance on this small generator family with deliberately strong planted events. They do **not** show expected accuracy on real exports or across cloud providers. The protocol, seeds, and caveats are in [`evaluation/REPORT.md`](evaluation/REPORT.md), with machine-readable results in [`evaluation/results.json`](evaluation/results.json); reproduce them with `python -m evaluation.run`.

## External sample smoke checks

Two public provider-format samples were used to probe the upload boundary. Both required a manual field mapping first; native provider exports are not directly supported.

| Public sample | Test result | What it establishes |
|---|---|---|
| [Microsoft FinOps Toolkit Azure test fixture](https://github.com/microsoft/finops-toolkit/blob/0eb91875d086c0bf488a826e964fcfecac9a67a5/src/powershell/Tests/Unit/assets/EA_AmortizedCost_Small.csv) | After mapping `Date`, `ConsumedService`, `Product`, `SubscriptionName`, `ResourceLocation`, `Cost`, and `BillingCurrency` to the canonical columns, the API accepted 28 rows across 9 observed dates and returned zero alerts. | A small positive-cost, provider-shaped CSV can pass through the normalized upload workflow. This is not an anomaly-accuracy result. |
| [FinOps Foundation FOCUS 1.0 sample](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data/blob/adbdd17a132984d6e8583c149c236d2199c3f5bc/FOCUS-1.0/focus_sample.csv) | The 1,000-row, 30-date sample had 13 negative `BilledCost` rows. After mapping its FOCUS date, service, SKU, account, region, cost, and currency fields, the API correctly rejected the file because the current schema requires non-negative costs. | The current contract does not accept a full sample containing negative adjustments or credits. No detector result was produced for this file. |

These are **compatibility smoke checks, not real-customer validation**. Microsoft describes its example exports as coming from an EA demo account and says they are not intended for ingestion or reporting ([Microsoft dataset notes](https://learn.microsoft.com/en-us/cloud-computing/finops/toolkit/open-data)). The FOCUS repository describes these as sample datasets and licenses them CC BY 4.0 ([sample repository](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data), [data license](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data/blob/main/license.md)); this project does not redistribute either file. Neither sample is evidence that the detector performs well on production billing data.

## Why no trained ML model

For this version, a trained model would add complexity without making the result more trustworthy: there is no representative, labeled customer-billing corpus to train or validate against. A history-based median and MAD rule is easy to reproduce, explain, inspect, and run without an API key or GPU.

That is a **trade-off, not a blanket advantage**:

- **Benefits:** deterministic results, transparent thresholds, low runtime cost, no model training pipeline, and direct evidence for each alert.
- **Costs:** hand-chosen thresholds; limited treatment of long seasonality, usage drivers, billing adjustments, and correlated dimensions; and weaker behavior with short histories or changing service mixes.

The optional LLM only summarizes calculated evidence; it does not detect anomalies, train on the uploaded file, or establish causes. A future model should be considered only after collecting appropriately permitted, representative data and showing a reproducible improvement over this baseline.

## Architecture and privacy

- FastAPI serves the API and static single-page interface from one container.
- CSV parsing and analysis are bounded and run in memory; the app does not write uploaded rows to disk or log them.
- No database, background worker, cloud-account connector, or required external service.
- Security response headers include a restrictive Content Security Policy. User-provided labels are rendered as text; chart values are escaped before SVG insertion.
- `/healthz` checks process health; `/readyz` also checks that the bundled sample is present.

| Endpoint | Purpose |
|---|---|
| `GET /api/sample` | Analyze the bundled synthetic sample |
| `GET /api/sample.csv` | Download the normalized synthetic CSV |
| `GET /api/sample/labels` | Inspect the planted synthetic events |
| `GET /api/schema` | Read supported fields and upload limits |
| `POST /api/analyze` | Analyze a normalized CSV body |
| `GET /api/report` | Download the bundled sample's JSON report |
| `GET /api/investigator/status` | Check whether optional AI summaries are configured |
| `POST /api/investigator` | Request an explicitly triggered, evidence-grounded summary |

The public demo has no authentication. Do not upload confidential billing data to a public deployment unless its access and data-handling setup is appropriate for that data. If the investigator is enabled, the selected file is uploaded to this app again on explicit action; only computed aggregate figures and service names are sent onward to the configured provider. Review that provider's terms before enabling it.

## Optional AI investigator

The core product works without an LLM. To enable the investigator, set `INVESTIGATOR_API_KEY` and `INVESTIGATOR_MODEL` on the server. Optionally set `INVESTIGATOR_CHAT_COMPLETIONS_URL` to an HTTPS OpenAI-compatible endpoint; otherwise it uses `https://api.openai.com/v1/chat/completions`.

Calls require an explicit user action, are limited in memory to three per minute per client and 30 per minute per process, and time out after eight seconds. Limits reset on process restart and are not shared across instances. The request contains computed evidence, not raw CSV rows. The response must cite each sentence; numeric claims must occur in the evidence cited by that sentence. Provider output remains untrusted text and is not treated as an action or infrastructure recommendation.

## Deployment recommendation

**Recommended target: Google Cloud Run.** This app already ships as one stateless container, needs no database or worker, and is compatible with request-based billing and scale-to-zero. Under request-based billing, Cloud Run charges for resources while handling requests and during instance startup/shutdown; its free-tier usage is aggregated by billing account and depends on region and billing configuration. [Cloud Run pricing](https://cloud.google.com/run/pricing) · [Billing behavior](https://docs.cloud.google.com/run/docs/configuring/billing-settings).

For a low-traffic public demo, use the prepared [Cloud Run rollout guide](deploy/README.md): minimum instances 0, a small CPU/memory configuration, and a low maximum instance count. Choose the region near the intended audience; Mumbai (`asia-south1`) is a reasonable first choice if most viewers are in India. The app has **not** been deployed yet, and this repository does not claim a guaranteed monthly bill. Cloud Build, Artifact Registry, and network transfer can add costs beyond Cloud Run compute.

Render Free is an alternative for a quick preview, but its free web services spin down after 15 minutes idle and can take about a minute to wake; Render says its free instances are for testing and hobby use, not production. That makes it less suitable for a polished always-ready portfolio demo. [Render free-service limits](https://render.com/docs/free).

Before deployment, choose a Google Cloud project and region, check current account eligibility and prices, and set an all-services budget alert. Google's Cloud Run spend cap is a Preview feature for eligible billing accounts; it pauses Cloud Run workloads project-wide when enforced, is not an exact invoice ceiling, and does not cover Cloud Build or Artifact Registry. Use a dedicated project if enabling it. [Spend-cap documentation](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps).

## Limitations and next steps

- Deploy a public Cloud Run revision and verify it from a clean browser session; deployment and live-URL verification are still pending.
- Add native provider-specific export adapters only if the project scope expands beyond normalized CSV.
- Validate on appropriately authorized, safely sanitized real-world billing exports before making claims about production accuracy.
- The detector does not model budgets, credits, commitments, billing adjustments, usage meters, or provider-specific export semantics.
- Negative cost rows (for example, some adjustments or credits) are rejected; a full export containing them must be reconciled or normalized before upload.
- Service attribution and the unexplained residual are estimates; the app does not infer causal explanations.
- There is no authentication, persistent history, team management, or cross-instance rate-limit store.

The public repository is source-ready and CI-verified. Do not call the hosted V1 shipped until a public URL is deployed, checked, and matched to the source commit.

## License

This project is released under the [Apache License 2.0](LICENSE).
