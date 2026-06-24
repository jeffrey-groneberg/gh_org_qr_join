# QR Org Join

A small Flask app that lets people self-join a GitHub organization by scanning a
per-org QR code. An **admin** manages the list of joinable orgs through an
Entra-protected CRUD UI and projects each org's QR code. A **participant** scans
the code, signs in with GitHub (identity only), and is invited into that org.

Member management — accepting invitations, roles, removals — stays on
GitHub.com. This app only creates the invitation.

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

## Deploy to Azure (Terraform)

Infrastructure lives in [`infra/`](infra/): a resource group, Linux App Service
Plan (B1) + Web App (Python, gunicorn), all app settings, and the Entra app
registration with an **admin** app role wired into App Service Easy Auth
("allow unauthenticated" so participants pass through).

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in values
terraform init
terraform apply
```

After apply, use the outputs to:
- set the GitHub OAuth App callback URL (`github_oauth_callback_url`),
- assign users to the admin app role (`admin_app_role_value`), unless you passed
  `admin_principal_object_ids`.

Then deploy the code (e.g. `az webapp up` or zip deploy); Oryx builds it from
`requirements.txt` and runs `gunicorn app:app`. SQLite is stored on the
persistent `/home` volume so data survives restarts.

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
- `admin.py` — org-list CRUD + QR page
- `participants.py` — GitHub OAuth identity + join
- `templates/` — server-rendered Jinja (GitHub dark theme)
- `infra/` — Terraform IaC for Azure
