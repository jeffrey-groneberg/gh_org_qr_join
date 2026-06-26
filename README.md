# QR Org Join

A small Flask app that lets people self-join a GitHub organization by scanning a
per-org QR code. An **admin** manages the list of joinable orgs through an
Entra-protected CRUD UI and projects each org's QR code. A **participant** scans
the code, signs in with GitHub (identity only), and is invited into that org.

Member management — accepting invitations, roles, removals — stays on
GitHub.com. This app only creates the invitation.

Orgs may be deleted on GitHub over time. When you **add** an org it is validated
against GitHub first — it is only added if the invite PAT can actually manage it
(send invitations); a non-existent org, one the PAT can't access, or one that
can't be verified is rejected with an explanation. From the admin list, **Check**
re-validates any org on demand and reports one of: it exists and the PAT can
invite (OK), it exists but the PAT can't manage it (no access), or it no longer
exists (missing) — in which case you're prompted to remove it from the list.

## How it works

1. The admin signs in (Entra ID, via App Service Easy Auth) and adds an org
   (its GitHub login/slug) to the list, then opens its QR code.
2. A participant scans the QR code, landing on `/orgs/<slug>`.
3. They click **Sign in with GitHub** — an OAuth App with *empty scope* tells us
   only their login.
4. They click **Join** — the server creates an org invitation using a single
   classic PAT (`admin:org`).
5. They accept the invitation on GitHub to finish joining.

### Three credentials, each at minimum privilege

| Credential | Purpose |
| --- | --- |
| Entra ID app role (via Easy Auth) | Authorizes the admin for the CRUD UI |
| GitHub OAuth App (empty scope) | Identifies the participant |
| GitHub classic PAT (`admin:org`) | Creates every org invitation |

No per-org secret is stored; each org is a small document (slug, display name,
join passcode) in **Cosmos DB for NoSQL** (serverless), accessed
passwordlessly via **managed identity** — the app holds no database keys.

## Run locally

Requires Python 3.10+ (the project targets 3.12, matching Azure).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in values (incl. COSMOS_ENDPOINT)
export ADMIN_DEV_BYPASS=1       # treat local user as admin (no Easy Auth locally)
az login                        # DefaultAzureCredential uses this for Cosmos
set -a; . ./.env; set +a
python app.py                   # http://127.0.0.1:8000
```

You'll need a GitHub OAuth App (callback `http://127.0.0.1:8000/callback`), a
classic PAT with `admin:org` for a test org you own, and a Cosmos DB account
(`COSMOS_ENDPOINT`) on which your user has the **Cosmos DB Built-in Data
Contributor** role — Terraform can grant it via `cosmos_data_principal_object_ids`.

Logs go to stdout at `LOG_LEVEL` (default INFO). Application Insights stays off
locally unless `APPLICATIONINSIGHTS_CONNECTION_STRING` is set.

## Deploy to Azure (step by step)

Infrastructure lives in [`infra/`](infra/): a resource group, Linux App Service
Plan (B1) + Web App (Python, gunicorn), all app settings, and the Entra app
registration with an **admin** app role wired into App Service Easy Auth
("allow unauthenticated" so participants pass through).

### Prerequisites
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) and
  [Terraform](https://developer.hashicorp.com/terraform/install) installed.
- An Azure subscription where you can create resources and an Entra app
  registration, plus rights to assign the app role (Application/Cloud App
  Administrator, or have an admin do the role assignment).
- Sign in: `az login` (Terraform uses this), and note your tenant ID
  (`az account show --query tenantId -o tsv`).

You do **not** need to invent an `app_name` — Terraform auto-generates a
globally-unique `qr-org-join-<random>` name. Because the GitHub OAuth App
callback depends on that name (and GitHub OAuth Apps can't be created via API),
deployment is two-phase. The `infra/1_app/deploy.sh` helper runs both phases for
you. (First apply the **`infra/0_bootstrap`** layer once — see
[CI/CD](#cicd-github-actions-oidc--no-stored-secrets) — which creates the
resource group, remote state, and CI identity.)

### 1. Create the invite PAT (classic, `admin:org`)
At <https://github.com/settings/tokens> → **Generate new token (classic)** with
the **`admin:org`** scope. The token owner must be an owner/admin of every org
participants will join. If an org enforces SAML SSO, authorize the token for it.

### 2. Seed Terraform variables
```bash
cd infra/1_app
cp terraform.tfvars.example terraform.tfvars
```
Set `tenant_id` (leave `app_name` empty to auto-generate). You can leave the
`github_*` values as placeholders for now — `deploy.sh` pauses for them once it
knows the URL. Optionally set `admin_principal_object_ids` to auto-assign
yourself the admin role (`az ad signed-in-user show --query id -o tsv`).

### 3. Deploy (two-phase, scripted)
```bash
./deploy.sh
```
The script:
1. uses Terraform to materialise the unique name (no Azure resources yet) and
   prints the exact **Homepage** and **callback** URLs;
2. pauses while you create the GitHub OAuth App at
   <https://github.com/settings/developers> with those URLs and paste its
   client ID/secret (and the PAT) into `terraform.tfvars`;
3. runs the full `terraform apply`;
4. prints the `az webapp up` command to deploy the code.

> Prefer to run it manually? Do
> `terraform apply -target=random_string.suffix` → `terraform output -raw app_url`
> to learn the URL, configure the OAuth App, fill in `terraform.tfvars`, then
> `terraform apply`.

### 4. Deploy the application code
From the repo root, using the name the script printed (or
`terraform -chdir=infra output -raw app_name`):
```bash
az webapp up \
  --name <app_name> \
  --resource-group rg-qr-org-join \
  --runtime "PYTHON:3.12"
```
This zips and uploads the code; App Service builds it with Oryx
(`pip install -r requirements.txt`) and runs `gunicorn app:app`. The SQLite
database is created automatically under the persistent `/home/data/` directory.

### 5. Grant admin access
If you didn't pass `admin_principal_object_ids`, assign users to the **admin**
app role: Entra admin center → **Enterprise applications** → `<app_name>-admin`
→ **Users and groups** → add users with the `admin_app_role_value` role.

### 6. Verify
- `<app_url>/healthz` → `{"status":"ok"}`.
- `/admin` redirects you through Entra sign-in; after consent you see the org
  list. Add an org, open its QR, scan it, and complete the GitHub join flow.

> **Custom / regional hostname:** all URLs derive from the resolved name. If
> Azure assigns a different hostname (custom domain or unique-default-hostname),
> set `app_base_url = "https://<actual-host>"` in `terraform.tfvars`, re-apply,
> and update the GitHub OAuth callback to match.

> **Dockerfile note:** the Azure deploy uses App Service's built-in Python
> runtime (Oryx), **not** the `Dockerfile`. The `Dockerfile` is kept only for
> local development and portability (`docker run`); it plays no part in the
> Terraform deployment.

## CI/CD (GitHub Actions, OIDC — no stored secrets)

Two path-filtered workflows so app releases never redeploy infra:

- **`.github/workflows/deploy-app.yml`** — runs on pushes that touch app code
  (`**.py`, `templates/**`, `requirements.txt`). Logs in via GitHub **OIDC** and
  ships the source to App Service (Oryx builds it). Uses a least-privilege
  identity (**Website Contributor on the Web App only**).
- **`.github/workflows/infra.yml`** — runs only on changes under `infra/1_app/**`.
  Plans on PRs, applies on pushes to `main`, gated behind the
  **`production-infra`** environment. Uses a separate, more-privileged identity.

Both authenticate with federated credentials (no client secret / publish
profile).

### Two Terraform layers (`infra/0_bootstrap`, `infra/1_app`)

Infra is split so the pipeline's own identity isn't managed by the pipeline:

- **`0_bootstrap`** (local state, run once by a human) — creates the application
  resource group, the Terraform remote-state Storage Account + container, and the
  privileged **infra CI identity** (UMI + federated credential + RBAC). This is
  the day-0 seed; everything it makes must exist before CI can run.
- **`1_app`** (remote state in that Storage Account, run by the infra workflow) —
  the App Service, Cosmos, App Insights, the Entra admin app, and the
  least-privilege **app-deploy identity**. It reads the resource group and infra
  identity from `0_bootstrap` via data sources.

From a fresh clone:

```bash
az login

# Day 0 — seed (human, local state):
cd infra/0_bootstrap
terraform init && terraform apply
terraform output            # note state account + identity values

# App layer (uses the remote backend created above):
cd ../1_app
terraform init \
  -backend-config="resource_group_name=$(terraform -chdir=../0_bootstrap output -raw state_resource_group_name)" \
  -backend-config="storage_account_name=$(terraform -chdir=../0_bootstrap output -raw state_storage_account_name)" \
  -backend-config="container_name=$(terraform -chdir=../0_bootstrap output -raw state_container_name)"
./deploy.sh                 # two-phase apply (prints GitHub OAuth URLs)
```

(The backend values are also baked into `1_app/backend.tf` as defaults.)

### Wire up GitHub (after the app layer is applied once)

Get the values from each layer's `terraform output`, then in the GitHub repo
create two **Environments** — `production` (app deploys) and `production-infra`
(infra; add required reviewers + restrict to `main`) — and set:

| Kind | Name | Value (source) |
| --- | --- | --- |
| Variable | `AZURE_WEBAPP_NAME` | `1_app` → `app_name` |
| Variable | `INFRA_IDENTITY_NAME` | `0_bootstrap` → `infra_identity_name` |
| Secret | `AZURE_CLIENT_ID` | `1_app` → `github_deploy_client_id` |
| Secret | `AZURE_INFRA_CLIENT_ID` | `0_bootstrap` → `infra_identity_client_id` |
| Secret | `AZURE_TENANT_ID` | your tenant ID |
| Secret | `AZURE_SUBSCRIPTION_ID` | your subscription ID |
| Secret | `TF_GITHUB_CLIENT_ID` | GitHub OAuth App client ID |
| Secret | `TF_GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret |
| Secret | `TF_GITHUB_INVITE_TOKEN` | GitHub `admin:org` PAT |

> The infra identity is an **owner** of the Entra admin app registration (set in
> `1_app/entra.tf`), which lets it manage that app without a directory-wide role.
> Assigning the admin **app role to users** (`admin_principal_object_ids`) still
> needs a directory admin; do that locally or in the portal.

## Layout

- `app.py` — pure app factory `create_app(config, store)` + composition root
- `config.py` — env-driven configuration (the only place that reads `os.environ`)
- `models.py` — `Org` dataclass (Cosmos document)
- `org_store.py` — `OrgStore` interface + `CosmosOrgStore` implementation
- `auth.py` — Easy Auth admin gate (`admin_required`)
- `github.py` — GitHub API helpers (`check_org_status`: ok/no_access/missing)
- `telemetry.py` — Azure Monitor / Application Insights wiring (config-driven)
- `admin.py` — org-list CRUD + QR page + org check
- `participants.py` — GitHub OAuth identity + join
- `templates/` — server-rendered Jinja (GitHub dark theme)
- `infra/0_bootstrap/` — day-0 Terraform: state account + infra CI identity
- `infra/1_app/` — application Terraform (App Service, Cosmos, Entra app, deploy identity)
- `.github/workflows/` — `deploy-app.yml` (app) and `infra.yml` (Terraform)

## Observability

Terraform provisions a **Log Analytics workspace** and a workspace-based
**Application Insights** component, and injects its connection string as the
`APPLICATIONINSIGHTS_CONNECTION_STRING` app setting. On startup the app calls
`telemetry.configure_telemetry()`, which uses Azure Monitor OpenTelemetry to
auto-instrument Flask requests, outbound GitHub calls, and the Python `logging`
module — so request traces, dependencies, and the app's own logs all flow to
Application Insights with trace correlation. View them under the
`<app_name>-ai` resource (Logs / Transaction search / Live metrics). Telemetry
is a no-op when the connection string is unset (e.g. local dev).
