# Cloud Run deployment

This repository is prepared for a single public Cloud Run service. The service is stateless, scales to zero, needs no database, and has no required provider key. Deployment has **not** been run yet.

## Before creating cloud resources

1. Choose a **dedicated Google Cloud project** for this demo and a deployment region. A dedicated project keeps a Cloud Run spend cap from pausing unrelated Cloud Run workloads.
2. If your billing account is eligible for Google's Preview spend caps, configure a project-scoped monthly **Cloud Run spend cap** at the amount you choose. Also create a project budget alert for all services to watch build and registry charges.
3. Confirm that billing is enabled and that the deployer has the required Cloud Run, Cloud Build, Artifact Registry, and service-account permissions.

An alerts-only budget does not stop spending. Google currently documents a Preview spend-cap budget for Cloud Run; when enforced, it pauses Cloud Run workloads across the selected project. Enforcement is delayed and in-flight/ongoing fixed costs can still accrue, so the cap is not an exact invoice ceiling. Cloud Build and Artifact Registry are separate services and are not covered by a Cloud Run service cap; use an all-services project budget alert for visibility. Availability is limited to eligible billing accounts. Check the current [Cloud Run pricing](https://cloud.google.com/run/pricing), [Cloud Build pricing](https://cloud.google.com/build/pricing), and [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing) before deployment. Google documents [source deployment and IAM roles](https://docs.cloud.google.com/run/docs/deploying-source-code), [budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets), and [Preview spend caps](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps).

## Deploy from Google Cloud Shell

Open Cloud Shell, clone the public repository, and set the chosen project and region. Replace the example region with the region you selected; do not assume free-tier eligibility.

```bash
git clone https://github.com/HariHaran9597/cloud-cost-anomaly-explainer.git
cd cloud-cost-anomaly-explainer
PROJECT_ID="your-project-id"
REGION="your-region"
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT_ID"
gcloud run deploy cloud-cost-anomaly-explainer \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 4 \
  --min 0 \
  --max 2 \
  --timeout 60
```

`--allow-unauthenticated` makes the demo public. The maximum of two instances bounds service scale, but is not a billing cap. Keep the optional investigator disabled by leaving its environment variables unset. Create the spend cap and all-services alert before deploying if the account supports them.

## Verify the deployed revision

Use the URL printed by `gcloud run deploy`:

```bash
SERVICE_URL="https://your-service-url"
curl --fail "$SERVICE_URL/healthz"
curl --fail "$SERVICE_URL/readyz"
curl --fail "$SERVICE_URL/api/sample"
```

Then open the URL in a clean browser session, load the bundled synthetic sample, confirm its two labeled alerts, and upload the bundled `app/data/sample_billing.csv`. Do not call V1 shipped until those checks pass and the deployed revision matches the repository commit.

## Rollback and remove

Use Cloud Run's revision traffic controls to roll back a bad revision. To remove the service when the demo is no longer needed:

```bash
gcloud run services delete cloud-cost-anomaly-explainer --project "$PROJECT_ID" --region "$REGION"
```

Removing the service does not necessarily delete its Artifact Registry image or Cloud Build history; review and remove those separately if desired.
