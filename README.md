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

No per-org secret is stored; the database holds only org slug, display name, and
default join role.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in values
export ADMIN_DEV_BYPASS=1       # treat local user as admin (no Easy Auth locally)
set -a; . ./.env; set +a
python app.py                   # http://127.0.0.1:8000
```

You'll need a GitHub OAuth App (callback `http://127.0.0.1:8000/callback`) and a
classic PAT with `admin:org` for a test org you own.

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
deployment is two-phase. The `infra/deploy.sh` helper runs both phases for you.

### 1. Create the invite PAT (classic, `admin:org`)
At <https://github.com/settings/tokens> → **Generate new token (classic)** with
the **`admin:org`** scope. The token owner must be an owner/admin of every org
participants will join. If an org enforces SAML SSO, authorize the token for it.

### 2. Seed Terraform variables
```bash
cd infra
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

## Layout

- `app.py` — application factory + WSGI entry (`gunicorn app:app`)
- `config.py` — env-driven configuration
- `extensions.py` — shared SQLAlchemy `db`
- `models.py` — `Org` model
- `auth.py` — Easy Auth admin gate (`admin_required`)
- `github.py` — GitHub API helpers (`check_org_status`: ok/no_access/missing)
- `admin.py` — org-list CRUD + QR page + org check
- `participants.py` — GitHub OAuth identity + join
- `templates/` — server-rendered Jinja (GitHub dark theme)
- `infra/` — Terraform IaC for Azure
