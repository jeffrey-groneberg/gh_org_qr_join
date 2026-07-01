#!/usr/bin/env bash
#
# Two-phase deploy for the QR Org Join app (single Terraform layer in infra/).
#
# Because the App Service hostname is auto-generated (app_name is left empty),
# the GitHub OAuth App's callback URL and the GitHub App's webhook URL can only
# be known after Terraform picks the name. GitHub Apps/OAuth Apps cannot be
# created via API/Terraform (UI-only), so this script:
#   1. materialises only random values (the unique name + webhook secret; no
#      Azure resources are created),
#   2. prints the exact URLs + webhook secret to configure your GitHub Apps,
#   3. waits for you to fill in the GitHub credentials,
#   4. runs the full apply,
#   5. prints the command to deploy the application code.
#
# Prerequisites: `az login` with sufficient roles (see README "Required roles"),
# Terraform installed, and terraform.tfvars created from terraform.tfvars.example
# (you can leave the github_* values blank until step 3 below).
#
# Usage:  ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> terraform init"
terraform init -input=false >/dev/null

echo "==> Resolving the unique app name + webhook secret (no Azure resources yet)"
terraform apply \
  -target=random_string.suffix \
  -target=random_password.webhook_secret \
  -auto-approve -input=false >/dev/null

APP_NAME="$(terraform output -raw app_name)"
APP_URL="$(terraform output -raw app_url)"
WEBHOOK_SECRET="$(terraform output -raw github_webhook_secret)"

cat <<EOF

------------------------------------------------------------------------
Your app will be deployed as:
  Name: ${APP_NAME}
  URL:  ${APP_URL}

1) Create/Update your GitHub OAuth App at
     https://github.com/settings/developers
   with:
     Homepage URL:               ${APP_URL}
     Authorization callback URL: ${APP_URL}/callback

   Create/Update your GitHub App at https://github.com/settings/apps with:
     Permissions:  Organization -> Members = Read & write
     Events:       Installation
     Webhook URL:  ${APP_URL}/webhooks/github
     Webhook secret (copy this exact value):
       ${WEBHOOK_SECRET}
     Generate a private key (.pem).

2) Put these into terraform.tfvars:
     github_client_id       = "<from the OAuth App>"
     github_client_secret   = "<from the OAuth App>"
     github_app_id          = "<GitHub App ID>"
     github_app_private_key = "<PEM contents of the App private key>"
------------------------------------------------------------------------
EOF

read -r -p "Press Enter once terraform.tfvars is ready to deploy everything... "

echo "==> terraform apply (full)"
terraform apply -input=false "$@"

RG="$(terraform output -raw resource_group_name)"

cat <<EOF

==> Infrastructure ready. Deploy the application code from the repo root:

    az webapp up --name ${APP_NAME} --resource-group ${RG} --runtime "PYTHON:3.12"

Then assign users to the admin app role (Enterprise applications ->
${APP_NAME}-admin) unless you set admin_principal_object_ids.
EOF
