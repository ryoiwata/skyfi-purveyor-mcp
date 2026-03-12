# Purveyor on GCP (Cloud Run + Cloud SQL + Secret Manager)

Deploys Purveyor to Google Cloud using Cloud Run for the application, Cloud SQL Postgres for persistence, and Secret Manager for credentials.

## Prerequisites

- Terraform >= 1.5.0
- `gcloud` CLI configured (`gcloud auth application-default login`)
- GCP project with billing enabled
- Docker image pushed to a registry

## Architecture

```
Internet → Cloud Run (Purveyor) → Cloud SQL Postgres (via Unix socket)
                               → Memorystore Redis (optional)
```

## Usage

```bash
cd deploy/terraform/gcp

# Copy and edit the example vars file
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your GCP project ID and domain

# Initialize
terraform init

# Review plan
terraform plan

# Apply
terraform apply
```

## Post-Deploy Setup

### 1. Set SKYFI_API_KEY in Secret Manager

```bash
echo -n "your-skyfi-api-key" | gcloud secrets versions add purveyor-skyfi-api-key --data-file=-
```

### 2. Get the Service URL

```bash
terraform output service_url
```

Configure your domain's DNS to point to this URL, or update `CONFIRMATION_BASE_URL` to use the Cloud Run URL directly.

### 3. Verify Health

```bash
curl $(terraform output -raw service_url)/health
```

## Estimated Monthly Cost (us-central1)

| Service | Config | ~Cost/month |
|---------|--------|-------------|
| Cloud Run | 0–10 instances, scales to zero | ~$0–20 |
| Cloud SQL | db-f1-micro, 10GB | ~$8 |
| Memorystore (optional) | 1GB Basic | ~$25 |
| **Total (without Redis)** | | **~$8–28** |
| **Total (with Redis)** | | **~$33–53** |

## Variables

See `variables.tf` for full documentation of all available variables.
