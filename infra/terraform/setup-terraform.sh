#!/usr/bin/env bash
# =============================================================================
# Phase 0 — Terraform Setup Script
# Run this from infra/terraform/ after GCP is set up.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR"
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_ENV="${PROJECT_ENV:-dev}"

echo "========================================"
echo "Terraform Setup for Product Copilot"
echo "========================================"
echo "Directory:  $TERRAFORM_DIR"
echo "AWS Region: $AWS_REGION"
echo "Environment: $PROJECT_ENV"
echo ""

# ---- 1. Check prerequisites ----
echo "[1/5] Checking prerequisites..."

command -v terraform >/dev/null 2>&1 || { echo "  ERROR: terraform not found. Install: https://developer.hashicorp.com/terraform/downloads"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "  ERROR: aws CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"; exit 1; }

echo "  terraform: $(terraform version | head -1)"
echo "  aws CLI: $(aws --version | awk '{print $1}')"

# ---- 2. Validate AWS credentials ----
echo "[2/5] Validating AWS credentials..."
AWS_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text)
AWS_USER=$(aws sts get-caller-identity --query 'Arn' --output text)
echo "  Account: $AWS_ACCOUNT"
echo "  User: $AWS_USER"

# ---- 3. Initialize Terraform ----
echo "[3/5] Initializing Terraform..."
cd "$TERRAFORM_DIR"
terraform init
echo "  OK — Terraform initialized"

# ---- 4. Format and validate ----
echo "[4/5] Formatting and validating Terraform..."
terraform fmt -recursive
terraform validate
echo "  OK — Terraform validated"

# ---- 5. Plan ----
echo "[5/5] Generating execution plan..."
echo "  Running: terraform plan -var-file=terraform.tfvars (if exists)"
echo ""
echo "  To apply:"
echo "    terraform plan -out=tfplan \\"
echo "      -var 'aws_region=${AWS_REGION}' \\"
echo "      -var 'project_env=${PROJECT_ENV}'"
echo ""
echo "    terraform apply tfplan"
echo ""
echo "  Or apply directly (will prompt for confirmation):"
echo "    terraform apply \\"
echo "      -var 'aws_region=${AWS_REGION}' \\"
echo "      -var 'project_env=${PROJECT_ENV}'"
echo ""
echo "========================================"
echo "Terraform setup ready. Run 'terraform apply' when ready."
echo "========================================"
