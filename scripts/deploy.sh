#!/usr/bin/env bash
set -euo pipefail

# Build and deploy Slack AI Assistant Lambda package locally.
# Usage: ./scripts/deploy.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Cleaning previous build"
rm -rf "$PROJECT_DIR/dist"
mkdir -p "$PROJECT_DIR/dist/package"

echo "==> Installing dependencies"
pip install -r "$PROJECT_DIR/requirements.txt" -t "$PROJECT_DIR/dist/package/" --quiet

echo "==> Copying handler and dependencies"
cp "$PROJECT_DIR/src/handler.py" "$PROJECT_DIR/dist/package/"
cp "$PROJECT_DIR/src/slack_client.py" "$PROJECT_DIR/dist/package/"
cp "$PROJECT_DIR/src/knowledge.py" "$PROJECT_DIR/dist/package/"

echo "==> Creating zip"
cd "$PROJECT_DIR/dist/package"
zip -r "$PROJECT_DIR/dist/lambda.zip" . -q

ZIPSIZE=$(du -h "$PROJECT_DIR/dist/lambda.zip" | cut -f1)
echo "==> Done: dist/lambda.zip ($ZIPSIZE)"
echo ""
echo "Next steps:"
echo "  cp terraform/terraform.tfvars.example terraform/terraform.tfvars"
echo "  # Edit terraform.tfvars with your Slack credentials and API keys"
echo "  cd terraform && terraform init"
echo "  terraform plan -out=tfplan && terraform apply tfplan"
