# Deploy to Vercel

This guide deploys the FastAPI application from the GitHub repository using Vercel's native Python runtime. The Dockerfile is used for container platforms; Vercel does not build or run it for this deployment. The app is stateless, has no database requirement, and works without an LLM/provider key. Deployment has **not** been completed until the checks below pass on the public URL.

## Before you start

- Have access to the GitHub repository `HariHaran9597/cloud-cost-anomaly-explainer` and a Vercel account.
- Use Vercel Hobby only for a personal, non-commercial demo. Check Vercel's [current plan terms and included limits](https://vercel.com/docs/plans/hobby).
- CSV uploads are capped at **4 MiB** by this app. Vercel Function request and response bodies are limited to **4.5 MB**, so the lower app limit leaves headroom for the platform boundary. [Vercel Function limits](https://vercel.com/docs/functions/limitations).
- Do not upload confidential billing exports to a public demo. The app has no user login or persistent history.

## Import the GitHub project

1. Open [vercel.com/new](https://vercel.com/new) and sign in.
2. Choose **Continue with GitHub** or connect GitHub when prompted. Approve access only to the project repository if Vercel offers repository-scoped access.
3. Select `HariHaran9597/cloud-cost-anomaly-explainer` and choose **Import**.
4. On **Configure Project**, set:
   - **Project name:** `cloud-cost-anomaly-explainer` (or another available name)
   - **Root Directory:** `./`
   - **Framework Preset:** `Other` if Vercel does not identify FastAPI automatically
   - **Build Command:** leave unset / use the detected default
   - **Output Directory:** leave unset
   - **Install Command:** leave the detected default
5. Leave **Environment Variables** empty for the baseline project. `INVESTIGATOR_API_KEY` is optional and is not needed for CSV analysis or the sample demo. Never put a provider key into frontend code or commit one to Git.
6. Select **Deploy** and wait for the build to finish.

Vercel reads the `tool.vercel.entrypoint` setting in `pyproject.toml` to load `app` from `app.main`. The FastAPI app serves its interface and API through that application. The project already includes the static UI and synthetic sample data in the repository bundle.

## Check the deployment

Copy the production URL shown by Vercel and open these paths, replacing `YOUR_URL` with that origin:

```text
https://YOUR_URL/healthz
https://YOUR_URL/readyz
https://YOUR_URL/api/schema
https://YOUR_URL/api/sample
https://YOUR_URL/api/sample.csv
https://YOUR_URL/api/investigator/status
```

Expected results:

- `/healthz` returns `{"status":"ok"}`.
- `/readyz` returns `{"status":"ready"}`.
- `/api/schema` reports `max_file_bytes` as `4194304`.
- `/api/sample` returns synthetic analysis with the sample labels and synthetic-data notice.
- `/api/sample.csv` downloads the bundled CSV.
- `/api/investigator/status` reports that the optional investigator is disabled.

Then use a private/incognito browser window to verify the public homepage, load the bundled sample in the UI, and upload the bundled CSV through the UI. Confirm the report and charts appear. Do not claim the hosted release is complete until these checks pass and the production deployment corresponds to the intended Git commit.

## Ongoing deployments and logs

Vercel can create preview deployments for Git changes and update production from the configured production branch (normally `main`). Check the deployment's **Build Logs** if installation or app detection fails, and **Runtime Logs** if a page returns a server error. Share the error text with credentials and environment variable values removed.

## Boundaries

- Hobby is for personal/non-commercial projects under Vercel's terms; check the current usage limits before sharing widely.
- Function uploads cannot exceed Vercel's 4.5 MB request-body limit; app CSV uploads stop at 4 MiB.
- Function instances are not durable storage. Uploaded CSVs are analyzed in memory and are not saved as user history.
- The optional LLM investigator is disabled by default. Enabling it requires a server-side key and causes selected aggregate evidence to be sent to the configured provider after the user explicitly requests an investigation.
- The public app has no authentication. Use synthetic or appropriately sanitized data only.
