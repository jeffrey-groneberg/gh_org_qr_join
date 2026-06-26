#!/usr/bin/env bash
#
# One-time bootstrap for the Terraform remote state backend.
#
# Creates the Azure Storage Account + container that hold terraform.tfstate, so
# both your laptop and GitHub Actions share one locked source of truth. This
# solves the chicken-and-egg problem (a remote backend needs the account to
# exist *before* `terraform init`): run this once per environment, then use
# Terraform normally.
#
# Safe to re-run: every step is idempotent. Uses Entra ID (AAD) auth — no
# storage account keys are used or stored.
#
# Usage:
#   az login
#   ./infra/bootstrap.sh
#
# Override defaults via env vars, e.g.:
#   TFSTATE_STORAGE_ACCOUNT=mystate ./infra/bootstrap.sh
#
set -euo pipefail

# --- Configuration (override via env vars) ---------------------------------
LOCATION="${TFSTATE_LOCATION:-westeurope}"
RESOURCE_GROUP="${TFSTATE_RESOURCE_GROUP:-rg-qr-org-join-tfstate}"
# Storage account names are global, 3-24 chars, lowercase alphanumeric only.
STORAGE_ACCOUNT="${TFSTATE_STORAGE_ACCOUNT:-qrorgjointfstate}"
CONTAINER="${TFSTATE_CONTAINER:-tfstate}"

echo "==> Terraform state backend bootstrap"
echo "    Resource group : $RESOURCE_GROUP"
echo "    Storage account: $STORAGE_ACCOUNT"
echo "    Container      : $CONTAINER"
echo "    Location       : $LOCATION"
echo

# --- Resource group (separate from the app RG so destroying app infra never
#     touches state) ---------------------------------------------------------
echo "==> Ensuring resource group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# --- Storage account: hardened, AAD-auth only ------------------------------
echo "==> Ensuring storage account..."
if ! az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --output none 2>/dev/null; then
  az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --https-only true \
    --output none
fi

# Enable blob versioning so an accidental bad state can be recovered.
az storage account blob-service-properties update \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --enable-versioning true \
  --output none

# --- Grant the current signed-in identity data-plane access ----------------
# Needed to create the container and to run Terraform locally with AAD auth.
echo "==> Granting current user data-plane access (Storage Blob Data Contributor)..."
CURRENT_ID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
SA_ID="$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"
if [ -n "$CURRENT_ID" ]; then
  az role assignment create \
    --assignee-object-id "$CURRENT_ID" \
    --assignee-principal-type User \
    --role "Storage Blob Data Contributor" \
    --scope "$SA_ID" \
    --output none 2>/dev/null || true
fi

# --- Container (created with AAD auth; retry while RBAC propagates) ---------
echo "==> Ensuring state container..."
for attempt in 1 2 3 4 5 6; do
  if az storage container create \
        --name "$CONTAINER" \
        --account-name "$STORAGE_ACCOUNT" \
        --auth-mode login \
        --output none 2>/dev/null; then
    break
  fi
  echo "    RBAC not propagated yet, retrying ($attempt)..."
  sleep 10
done

echo
echo "==> Done. Initialize Terraform against the remote backend with:"
echo
echo "    cd infra"
echo "    terraform init \\"
echo "      -backend-config=\"resource_group_name=$RESOURCE_GROUP\" \\"
echo "      -backend-config=\"storage_account_name=$STORAGE_ACCOUNT\" \\"
echo "      -backend-config=\"container_name=$CONTAINER\""
echo
echo "    (These values are also baked into backend.tf as defaults.)"
