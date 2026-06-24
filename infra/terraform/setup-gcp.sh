#!/usr/bin/env bash
# =============================================================================
# Phase 0 — GCP Setup Script
# Run this to set up GCP project, service account, and enable Vertex AI.
# =============================================================================

set -euo pipefail

GCP_PROJECT_ID="${GCP_PROJECT_ID:-avid-day-498316-e4}"
GCP_REGION="${GCP_REGION:-us-central1}"
SA_NAME="copilot-adk"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
KEY_FILE="${HOME}/.config/gcloud/product-copilot-sa-key.json"

echo "========================================"
echo "GCP Setup for Product Copilot"
echo "========================================"
echo "Project:   $GCP_PROJECT_ID"
echo "Region:    $GCP_REGION"
echo "SA Email:  $SA_EMAIL"
echo ""

# ---- 1. Authenticate ----
echo "[1/6] Checking gcloud authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "Not authenticated. Run: gcloud auth login"
    exit 1
fi
echo "  OK — authenticated as: $(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)"

# ---- 2. Set project ----
echo "[2/6] Setting active project..."
gcloud config set project "$GCP_PROJECT_ID"
echo "  OK — project set to: $GCP_PROJECT_ID"

# ---- 3. Enable Vertex AI API ----
echo "[3/6] Enabling Vertex AI API..."
gcloud services enable aiplatform.googleapis.com --quiet
echo "  OK — Vertex AI API enabled"

# ---- 4. Create or confirm service account ----
echo "[4/6] Creating service account..."
if gcloud iam service-accounts describe "$SA_EMAIL" --quiet 2>/dev/null; then
    echo "  Service account already exists: $SA_EMAIL"
else
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Product Copilot ADK" \
        --description="Service account for Product Copilot Google ADK"
    echo "  Created: $SA_EMAIL"
fi

# ---- 5. Grant Vertex AI permissions ----
echo "[5/6] Granting Vertex AI permissions to service account..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/aiplatform.user" \
    --quiet

# Also grant the token creator role (needed for service account key auth)
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --quiet
echo "  OK — roles/aiplatform.user + roles/iam.serviceAccountTokenCreator granted"

# ---- 6. Download service account key ----
echo "[6/6] Downloading service account key..."
mkdir -p "$(dirname "$KEY_FILE")"
if [ -f "$KEY_FILE" ]; then
    echo "  Key file already exists at: $KEY_FILE"
    echo "  Skipping download (delete the file to re-download)"
else
    gcloud iam service-accounts keys create "$KEY_FILE" \
        --iam-account="$SA_EMAIL" \
        --quiet
    echo "  Downloaded to: $KEY_FILE"
    echo "  IMPORTANT: This file is in your home directory."
    echo "             It will be uploaded to AWS Secrets Manager in the next step."
fi

echo ""
echo "========================================"
echo "GCP Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Upload the SA key to AWS Secrets Manager:"
echo "     aws secretsmanager create-secret \\"
echo "       --name product-copilot/gcp-sa-key \\"
echo "       --secret-string file://${KEY_FILE}"
echo ""
echo "  2. Verify Vertex AI access:"
echo "     GOOGLE_APPLICATION_CREDENTIALS=${KEY_FILE} \\"
echo "       python3 -c \\"
echo "         'import vertexai; vertexai.init(project=\"${GCP_PROJECT_ID}\", location=\"${GCP_REGION}\"); print(\"OK\")'"
echo ""
echo "  3. Proceed to Terraform setup (infra/terraform/)"
