# Phase 0 — Infrastructure Setup

**Goal:** Provision all cloud infrastructure before writing any application code.

---

## Overview

Phase 0 sets up three cloud environments:

| Service | Provider | Purpose |
|---|---|---|
| **Vertex AI** | GCP | Gemini LLM + text-embedding-004 |
| **Qdrant Cloud** | Qdrant (managed) | Vector database |
| **All other resources** | AWS | ECS, RDS, Redis, S3, Secrets Manager, etc. |

GCP is used **only** for LLM calls. All other infrastructure runs on AWS.

---

## Step 1 — GCP Setup (~20 minutes)

### Prerequisites
```bash
# Install gcloud CLI
brew install google-cloud-sdk

# Authenticate
gcloud auth login

# Set default region
gcloud config set compute/region us-central1
```

### Run the GCP setup script
```bash
cd infra/terraform

# Set your GCP project ID (create one at console.cloud.google.com if needed)
export GCP_PROJECT_ID="product-copilot-dev"

# Run setup
make gcp
# or directly:
PROJECT_ID="product-copilot-dev" bash setup-gcp.sh
```

**What this does:**
1. Enables Vertex AI API
2. Creates service account `copilot-adk@<project>.iam.gserviceaccount.com`
3. Grants `roles/aiplatform.user` permission
4. Downloads JSON key to `~/.config/gcloud/product-copilot-sa-key.json`

---

## Step 2 — Qdrant Cloud Setup (~10 minutes)

1. Go to [cloud.qdrant.io](https://cloud.qdrant.io) and sign up
2. Create a cluster:
   - Name: `product-copilot`
   - Region: closest to your AWS region (e.g., `us-east-1`)
3. Copy the API key from the dashboard
4. Test the connection:
   ```python
   from qdrant_client import QdrantClient
   client = QdrantClient(url="https://your-cluster.qdrant.io", api_key="your-key")
   print(client.get_collections())
   ```

---

## Step 3 — Terraform on AWS (~30 minutes)

### Prerequisites
```bash
# Install Terraform
brew install terraform

# Authenticate AWS CLI
aws configure

# Verify credentials
aws sts get-caller-identity
```

### Initialize and apply
```bash
cd infra/terraform

# Initialize (downloads providers)
make terraform-init

# Format and validate
make terraform-fmt

# Plan (preview what will be created)
make terraform-plan

# Apply (creates all infrastructure — prompts for confirmation)
make terraform-apply
```

**What Terraform creates:**

| Resource | Name |
|---|---|
| VPC | `product-copilot-vpc` (10.0.0.0/16) |
| RDS PostgreSQL | `product-copilot-db` (t4g.micro, 20GB) |
| ElastiCache Redis | `product-copilot-redis` (t4g.micro) |
| ECS Cluster | `product-copilot-dev` |
| ALB | `product-copilot-alb` |
| S3 Bucket | `product-copilot-artifacts-*` |
| Secrets Manager | 5 secrets (empty values) |
| IAM Roles | 2 roles (execution + task) |
| CloudWatch Log Group | `/ecs/product-copilot-dev` |

---

## Step 4 — Fill Secrets (~15 minutes)

After `terraform apply` completes, fill in the secrets that Terraform created as empty placeholders:

```bash
# GCP Service Account Key
aws secretsmanager put-secret-value \
  --secret-id product-copilot/gcp-sa-key \
  --secret-string file://$HOME/.config/gcloud/product-copilot-sa-key.json

# Slack Bot Token (from Slack App settings)
aws secretsmanager put-secret-value \
  --secret-id product-copilot/slack-bot-token \
  --secret-string "xoxb-your-real-token"

# Slack Signing Secret
aws secretsmanager put-secret-value \
  --secret-id product-copilot/slack-signing-secret \
  --secret-string "your-slack-signing-secret"

# Qdrant API Key
aws secretsmanager put-secret-value \
  --secret-id product-copilot/qdrant-api-key \
  --secret-string "your-qdrant-api-key"
```

Or run:
```bash
make secrets-fill
```

---

## Verification Checklist

After all steps complete:

- [ ] `gcloud` CLI authenticated
- [ ] `roles/aiplatform.user` role granted to service account
- [ ] `python3 -c "import vertexai; vertexai.init(...)"` succeeds
- [ ] Qdrant Cloud cluster accessible from Python
- [ ] `terraform apply` completed without error
- [ ] RDS PostgreSQL accessible (check AWS Console → RDS → product-copilot-db)
- [ ] ElastiCache Redis accessible (check AWS Console → ElastiCache → product-copilot-redis)
- [ ] ECS cluster visible (AWS Console → ECS → product-copilot-dev)
- [ ] ALB DNS name available (AWS Console → EC2 → Load Balancers → product-copilot-alb)
- [ ] All 5 secrets in Secrets Manager with real values

Run `make verify-all` to check status.

---

## Expected Time

| Step | Time |
|---|---|
| GCP setup | 20 minutes |
| Qdrant Cloud | 10 minutes |
| Terraform apply | 15–30 minutes |
| Fill secrets | 15 minutes |
| **Total** | **~1–1.5 hours** |

---

## What Comes Next

After Phase 0 is complete, proceed to **Phase 1A**:
- Create the project structure
- Write the FastAPI application
- Containerize with Docker
- Deploy to ECS Fargate
- Verify `/health` returns ok from the ALB
