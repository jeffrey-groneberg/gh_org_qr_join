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
#   2. prints the exact URLs + webhook secret as four colour-coded tasks to set
#      up your GitHub OAuth App / GitHub App,
#   3. waits for you to complete them, then validates the GitHub credentials,
#   4. runs the full apply,
#   5. prints the command to deploy the application code.
#
# Prerequisites: `az login` with sufficient roles (see README "Required roles"),
# Terraform installed, and terraform.tfvars created from terraform.tfvars.example
# (you can leave the github_* values blank until step 3 below). GitHub credential
# validation uses `curl` + `openssl` only — no Python required.
#
# Usage:  ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

# --- Colors (disabled when not a TTY or when NO_COLOR is set) ----------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  BLUE=$'\033[34m'; MAGENTA=$'\033[35m'; CYAN=$'\033[36m'
else
  BOLD=; RESET=; RED=; GREEN=; YELLOW=; BLUE=; MAGENTA=; CYAN=
fi
step() { printf '%s==>%s %s\n' "${BOLD}${CYAN}" "${RESET}" "$*"; }
ok()   { printf '    %s✓%s %s\n' "${GREEN}" "${RESET}" "$*"; }
warn() { printf '    %s!%s %s\n' "${YELLOW}" "${RESET}" "$*"; }
# fail <title>: print a red banner; caller adds indented guidance lines, then exit.
fail() { printf '\n%s✖ %s%s\n' "${BOLD}${RED}" "$*" "${RESET}" >&2; }

# --- GitHub credential validation (curl + openssl; no Python) ---------------
_tfvar() {
  # Extract a simple quoted string value for key $1 from terraform.tfvars.
  [ -f terraform.tfvars ] || return 0
  sed -nE "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\"([^\"]*)\".*/\1/p" \
    terraform.tfvars | head -1
}
_b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

validate_github_credentials() {
  if ! command -v curl >/dev/null 2>&1 || ! command -v openssl >/dev/null 2>&1; then
    warn "Skipping GitHub credential validation (need both 'curl' and 'openssl' on PATH)."
    return 0
  fi
  step "Validating GitHub credentials"

  local cid csecret appid oc
  local missing=()
  cid="$(_tfvar github_client_id)"
  csecret="$(_tfvar github_client_secret)"
  appid="$(_tfvar github_app_id)"

  [ -z "${cid}" ] && missing+=("github_client_id")
  [ -z "${csecret}" ] && missing+=("github_client_secret")
  [ -z "${appid}" ] && missing+=("github_app_id")
  if [ "${#missing[@]}" -gt 0 ]; then
    fail "Missing values in terraform.tfvars"
    printf '    These variables are empty or absent: %s%s%s\n' "${YELLOW}" "${missing[*]}" "${RESET}" >&2
    printf '    Add them (see Task 1 and Task 4 above), then re-run ./deploy.sh\n' >&2
    exit 1
  fi

  # OAuth App: "check a token". With correct client_id + client_secret (basic
  # auth), GitHub accepts the request and reports on the token: 200 if it somehow
  # existed, or 404/422 for our throwaway probe token — all of which mean the
  # CREDENTIALS are valid. Only 401 means the client_id/secret were rejected.
  oc=$(curl -s -o /dev/null -w '%{http_code}' -u "${cid}:${csecret}" \
    -X POST -H "Accept: application/vnd.github+json" \
    "https://api.github.com/applications/${cid}/token" \
    -d '{"access_token":"invalid-probe-token"}' || echo "000")
  case "${oc}" in
    200 | 404 | 422) ok "OAuth App credentials accepted by GitHub." ;;
    401)
      fail "OAuth App credentials rejected by GitHub (HTTP 401)."
      {
        printf '    Cause: github_client_id / github_client_secret in terraform.tfvars do not\n'
        printf '           match a real GitHub OAuth App (or GitHub App client id/secret).\n'
        printf '    Fix:\n'
        printf '      1. Open %shttps://github.com/settings/developers%s  →  your OAuth App\n' "${BLUE}" "${RESET}"
        printf '      2. Copy the Client ID           →  github_client_id\n'
        printf '      3. Generate a new client secret →  github_client_secret\n'
        printf '      4. Ensure the Authorization callback URL is exactly:\n'
        printf '           %s%s/callback%s\n' "${BOLD}" "${APP_URL}" "${RESET}"
        printf '    Then re-run ./deploy.sh\n'
      } >&2
      exit 1
      ;;
    000) warn "OAuth App check skipped — could not reach api.github.com (network?)." ;;
    *) warn "OAuth App check: unexpected HTTP ${oc} — continuing." ;;
  esac

  # GitHub App: mint a short RS256 JWT from the PEM and call GET /app — 200 when
  # the App ID and private key are valid and match.
  local now iat exp header payload signing_input sig jwt ac
  now=$(date +%s); iat=$((now - 60)); exp=$((now + 300))
  header=$(printf '{"alg":"RS256","typ":"JWT"}' | _b64url)
  payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "${iat}" "${exp}" "${appid}" | _b64url)
  signing_input="${header}.${payload}"
  if ! sig=$(printf '%s' "${signing_input}" | openssl dgst -sha256 -sign "${PEM_FILE}" -binary 2>/dev/null | _b64url); then
    fail "Could not sign a token with ${PEM_FILE}."
    {
      printf '    Cause: the file is not a valid RSA private key (PEM).\n'
      printf '    Fix:  re-download the private key from your GitHub App and save it as:\n'
      printf '            %s%s%s\n' "${BOLD}" "${PEM_FILE}" "${RESET}"
      printf '          It must start with "-----BEGIN RSA PRIVATE KEY-----".\n'
    } >&2
    exit 1
  fi
  jwt="${signing_input}.${sig}"
  ac=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${jwt}" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/app || echo "000")
  case "${ac}" in
    200) ok "GitHub App ID and private key accepted by GitHub." ;;
    401)
      fail "GitHub App authentication failed (HTTP 401)."
      {
        printf '    Cause: github_app_id and github-app.pem do not match a real GitHub App\n'
        printf '           (wrong App ID, or the .pem was generated for a different App).\n'
        printf '    Fix:\n'
        printf '      1. Open %shttps://github.com/settings/apps%s  →  your App  →  "About"\n' "${BLUE}" "${RESET}"
        printf '      2. Copy the numeric "App ID"    →  github_app_id\n'
        printf '      3. Under "Private keys", Generate a private key and save it as:\n'
        printf '           %s%s%s   (replace any old one)\n' "${BOLD}" "${PEM_FILE}" "${RESET}"
        printf '    Then re-run ./deploy.sh\n'
      } >&2
      exit 1
      ;;
    000) warn "GitHub App check skipped — could not reach api.github.com (network?)." ;;
    *) warn "GitHub App check: unexpected HTTP ${ac} — continuing." ;;
  esac
}

# terraform.tfvars must exist before anything runs: even phase 1 evaluates the
# required variables. Guide the user to create it from the template if missing.
if [ ! -f terraform.tfvars ]; then
  fail "terraform.tfvars not found."
  {
    printf '    Create it from the template, then open it in your editor:\n'
    printf '      %scp terraform.tfvars.example terraform.tfvars%s\n' "${BOLD}" "${RESET}"
    printf '    Before re-running, set at least:\n'
    printf '      operator_ip_cidr  (your public IP as x.x.x.x/32, e.g. %scurl -s https://api.ipify.org%s)\n' "${BLUE}" "${RESET}"
    printf '    You can leave the github_* values as placeholders — this script prints\n'
    printf '    the URLs you need first, then pauses for you to fill them in.\n'
    printf '    Then re-run ./deploy.sh\n'
  } >&2
  exit 1
fi

step "terraform init"
terraform init -input=false >/dev/null

step "Resolving the unique app name + webhook secret (no Azure resources yet)"
terraform apply \
  -target=random_string.suffix \
  -target=random_password.webhook_secret \
  -auto-approve -input=false >/dev/null

APP_NAME="$(terraform output -raw app_name)"
APP_URL="$(terraform output -raw app_url)"
WEBHOOK_SECRET="$(terraform output -raw github_webhook_secret)"

cat <<EOF

${BOLD}────────────────────────────────────────────────────────────────────────${RESET}
Your app will be deployed as:
  Name: ${BOLD}${APP_NAME}${RESET}
  URL:  ${BOLD}${APP_URL}${RESET}

Complete these four tasks, then press Enter to continue.
${BOLD}(${RED}Red values${RESET}${BOLD} are exact strings to copy & paste for a later step.)${RESET}

${BOLD}${BLUE}TASK 1 — GitHub OAuth App${RESET}  (identifies the participant)
  Create/Update it at ${BLUE}https://github.com/settings/developers${RESET}
    Homepage URL:               ${BOLD}${RED}${APP_URL}${RESET}
    Authorization callback URL: ${BOLD}${RED}${APP_URL}/callback${RESET}
  Then copy its Client ID + a new client secret (used in Task 4).

${BOLD}${MAGENTA}TASK 2 — GitHub App${RESET}  (sends invitations + Copilot seats + webhook)
  Create/Update it at ${MAGENTA}https://github.com/settings/apps${RESET}
    Permissions → Organization → Members               = Read & write
    Permissions → Organization → GitHub Copilot Business = Read & write
    Subscribe to events:  Installation
    Webhook URL:    ${BOLD}${RED}${APP_URL}/webhooks/github${RESET}
    Webhook secret: ${BOLD}${RED}${WEBHOOK_SECRET}${RESET}
  Then note its numeric App ID (used in Task 4).

${BOLD}${CYAN}TASK 3 — Save the GitHub App private key${RESET}
  In the GitHub App, "Generate a private key", then save the downloaded .pem as:
    ${BOLD}$(pwd)/github-app.pem${RESET}
  (gitignored; Terraform reads it from there — you never paste its contents.)

${BOLD}${YELLOW}TASK 4 — Fill terraform.tfvars${RESET}
    github_client_id     = "<Client ID from Task 1>"
    github_client_secret = "<client secret from Task 1>"
    github_app_id        = "<App ID from Task 2>"
  (The webhook secret lives in Terraform state; the private key is the .pem file —
   neither goes in terraform.tfvars.)
${BOLD}────────────────────────────────────────────────────────────────────────${RESET}
EOF

read -r -p "Press Enter once all four tasks are done to deploy everything... "

PEM_FILE="$(pwd)/github-app.pem"
if [ ! -f "${PEM_FILE}" ]; then
  fail "GitHub App private key not found."
  {
    printf '    Expected the .pem here (Task 3):\n'
    printf '      %s%s%s\n' "${BOLD}" "${PEM_FILE}" "${RESET}"
    printf '    In your GitHub App (%shttps://github.com/settings/apps%s), under\n' "${BLUE}" "${RESET}"
    printf '    "Private keys", Generate a private key and save the download to that path.\n'
  } >&2
  exit 1
fi

validate_github_credentials

step "terraform apply (full)"
terraform apply -input=false "$@"

RG="$(terraform output -raw resource_group_name)"

cat <<EOF

${BOLD}${GREEN}✓ Infrastructure ready.${RESET} Deploy the application code from the repo root:

    ${BOLD}${RED}az webapp up --name ${APP_NAME} --resource-group ${RG} --runtime "PYTHON:3.12"${RESET}

(${BOLD}${RED}Red${RESET} = copy & paste this command to deploy your code.)

Then assign users to the admin app role (Enterprise applications ->
${APP_NAME}-admin) unless you set admin_principal_object_ids.
EOF
