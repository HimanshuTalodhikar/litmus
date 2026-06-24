.PHONY: help gcp terraform terraform-apply terraform-destroy secrets-check

AWS_REGION  ?= us-east-1
PROJECT_ENV  ?= dev
GCP_PROJECT  ?= product-copilot-dev
GCP_REGION   ?= us-central1

help:
	@echo "Phase 0 — Infrastructure Setup"
	@echo ""
	@echo "Prerequisites:"
	@echo "  - gcloud CLI installed and authenticated"
	@echo "  - aws CLI installed and authenticated"
	@echo "  - Terraform >= 1.5 installed"
	@echo "  - Qdrant Cloud account created (cloud.qdrant.io)"
	@echo ""
	@echo "Commands:"
	@echo "  make gcp                Set up GCP project, service account, Vertex AI"
	@echo "  make qdrant            Print Qdrant Cloud setup instructions"
	@echo "  make terraform-init     Initialize Terraform"
	@echo "  make terraform-plan     Plan Terraform changes"
	@echo "  make terraform-apply    Apply Terraform (creates AWS infrastructure)"
	@echo "  make terraform-destroy  Destroy all Terraform-managed resources"
	@echo "  make secrets-fill      Print instructions to fill Secrets Manager values"
	@echo "  make verify            Verify all infrastructure is set up correctly"
	@echo ""
	@echo "Variables:"
	@echo "  GCP_PROJECT=$(GCP_PROJECT)"
	@echo "  GCP_REGION=$(GCP_REGION)"
	@echo "  AWS_REGION=$(AWS_REGION)"
	@echo "  PROJECT_ENV=$(PROJECT_ENV)"

# ── GCP Setup ─────────────────────────────────────────────────────────────────

gcp:
	@echo "Running GCP setup..."
	@PROJECT_ID=$(GCP_PROJECT) REGION=$(GCP_REGION) bash infra/terraform/setup-gcp.sh

verify-gcp:
	@echo "Verifying GCP Vertex AI access..."
	@GOOGLE_APPLICATION_CREDENTIALS=$$HOME/.config/gcloud/product-copilot-sa-key.json \
	  python3 -c "import vertexai; vertexai.init(project='$(GCP_PROJECT)', location='$(GCP_REGION)'); print('✅ Vertex AI access OK')" \
	|| echo "❌ Vertex AI access failed — check credentials"

# ── Qdrant ────────────────────────────────────────────────────────────────────

qdrant:
	@echo "Qdrant Cloud Setup Instructions:"
	@echo ""
	@echo "1. Go to https://cloud.qdrant.io and sign up"
	@echo "2. Create a cluster:"
	@echo "     Name: product-copilot"
	@echo "     Region: us-east-1 (or closest to your AWS region)"
	@echo "3. Copy your API key from the dashboard"
	@echo "4. Store in AWS Secrets Manager:"
	@echo ""
	@echo "   aws secretsmanager create-secret \\"
	@echo "     --name product-copilot/qdrant-api-key \\"
	@echo "     --secret-string 'YOUR_QDRANT_API_KEY'"
	@echo ""
	@echo "5. Test connection:"
	@echo "   python3 -c \"\\"
	@echo "     from qdrant_client import QdrantClient;\\"
	@echo "     client = QdrantClient(url='YOUR_CLUSTER_URL', api_key='YOUR_KEY');\\"
	@echo "     print(client.get_collections())\""
	@echo ""

# ── Terraform ─────────────────────────────────────────────────────────────────

terraform-init:
	cd infra/terraform && terraform init

terraform-plan:
	cd infra/terraform && terraform plan \
		-var "aws_region=$(AWS_REGION)" \
		-var "project_env=$(PROJECT_ENV)" \
		-out=tfplan

terraform-apply:
	cd infra/terraform && terraform apply tfplan

terraform-destroy:
	cd infra/terraform && terraform destroy \
		-var "aws_region=$(AWS_REGION)" \
		-var "project_env=$(PROJECT_ENV)"

terraform-fmt:
	cd infra/terraform && terraform fmt -recursive && terraform validate

# ── Secrets ────────────────────────────────────────────────────────────────────

secrets-fill:
	@echo "========================================"
	@echo "Secrets to Fill in AWS Secrets Manager"
	@echo "========================================"
	@echo ""
	@echo "Run these commands AFTER terraform apply completes:"
	@echo ""
	@echo "1. GCP Service Account Key:"
	@echo "   aws secretsmanager put-secret-value \\"
	@echo "     --secret-id product-copilot/gcp-sa-key \\"
	@echo "     --secret-string file://$$HOME/.config/gcloud/product-copilot-sa-key.json"
	@echo ""
	@echo "2. Slack Bot Token (from Slack App settings):"
	@echo "   aws secretsmanager put-secret-value \\"
	@echo "     --secret-id product-copilot/slack-bot-token \\"
	@echo "     --secret-string 'xoxb-your-token-here'"
	@echo ""
	@echo "3. Slack Signing Secret:"
	@echo "   aws secretsmanager put-secret-value \\"
	@echo "     --secret-id product-copilot/slack-signing-secret \\"
	@echo "     --secret-string 'your-signing-secret-here'"
	@echo ""
	@echo "4. Qdrant API Key:"
	@echo "   aws secretsmanager put-secret-value \\"
	@echo "     --secret-id product-copilot/qdrant-api-key \\"
	@echo "     --secret-string 'your-qdrant-api-key'"
	@echo ""
	@echo "5. Vertex AI API Key (optional, if not using SA key):"
	@echo "   aws secretsmanager put-secret-value \\"
	@echo "     --secret-id product-copilot/vertex-api-key \\"
	@echo "     --secret-string 'your-vertex-api-key'"

secrets-list:
	@echo "Checking Secrets Manager..."
	@aws secretsmanager list-secrets \
	  --filter Key=name,Values=product-copilot \
	  --query 'SecretList[].Name' \
	  --output table

# ── Verification ───────────────────────────────────────────────────────────────

verify-all:
	@echo "========================================"
	@echo "Phase 0 Verification Checklist"
	@echo "========================================"
	@echo ""
	@echo "Checking GCP..."
	@GOOGLE_APPLICATION_CREDENTIALS=$$HOME/.config/gcloud/product-copilot-sa-key.json \
	  python3 -c "import vertexai; vertexai.init(project='$(GCP_PROJECT)', location='$(GCP_REGION)'); print('✅ GCP Vertex AI OK')" \
	2>/dev/null || echo "⚠️  GCP — run: make verify-gcp"
	@echo ""
	@echo "Checking Qdrant Cloud..."
	@echo "⚠️  Manually verify Qdrant Cloud at cloud.qdrant.io"
	@echo ""
	@echo "Checking Terraform state..."
	@cd infra/terraform && \
	  terraform show -no-color > /dev/null 2>&1 \
	  && echo "✅ Terraform state OK" \
	  || echo "⚠️  Terraform state not initialized — run: make terraform-init"
	@echo ""
	@echo "Checking Secrets..."
	@make secrets-list 2>/dev/null || echo "⚠️  AWS CLI not configured"
