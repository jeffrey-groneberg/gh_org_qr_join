# Copilot instructions — QR Org Join

A small Flask app that lets people self-join a GitHub organization by scanning a
per-org QR code. An admin manages the list of joinable orgs through an
Entra-protected CRUD UI; participants scan a code, sign in with GitHub, and are
invited into that org. The app never administers members itself — invitation
acceptance, roles, and removals all happen on GitHub.com.

## Run, build, deploy

There is no automated test suite or linter configured; do not invent commands
for them. Validate changes by building the app factory (below).

- Local run: install deps into the venv, load env vars, then start Flask:
  ```bash
  pip install -r requirements.txt
  cp .env.example .env   # then fill in values
  export ADMIN_DEV_BYPASS=1   # treat local user as admin (no Easy Auth locally)
  set -a; . ./.env; set +a
  python app.py          # or: flask --app app run --debug --port 8000
  ```
  `app.py` exposes the WSGI callable `app` (so `gunicorn app:app` works).
- Smoke-test the factory without a server or Cosmos (inject a fake store from
  outside — the app has no test/env awareness):
  ```bash
  FLASK_SECRET_KEY=x APP_BASE_URL=http://127.0.0.1:8000 \
  COSMOS_ENDPOINT=https://dummy.documents.azure.com:443/ \
  GITHUB_CLIENT_ID=x GITHUB_CLIENT_SECRET=x GITHUB_INVITE_TOKEN=x ADMIN_DEV_BYPASS=1 \
  python -c "import app; from config import Config; \
    a=app.create_app(Config(), object()); print(sorted(str(r) for r in a.url_map.iter_rules()))"
  ```
  (`object()` stands in for any `OrgStore`; provide a real fake to exercise routes.)
- The venv (`.venv`) targets Python 3.12 (matching the Azure runtime); type
  hints use `from __future__ import annotations`.
- Container: `Dockerfile` runs `gunicorn --bind 0.0.0.0:${PORT} app:app` as a
  non-root user — **local dev / portability only**. The Azure deploy uses App
  Service's built-in Python runtime (Oryx), not this image. All config is via
  env vars — see `.env.example`.
- Deploy: Terraform is split into two layers. `infra/0_bootstrap/` (day-0, local
  state, human-run) creates the resource group, the remote-state Storage Account,
  and the privileged GitHub OIDC **infra** identity. `infra/1_app/` (remote state,
  run by the infra workflow) provisions App Service + Entra Easy Auth + Cosmos DB
  (serverless) + Application Insights + the least-privilege **app-deploy**
  identity, reading the RG and infra identity from `0_bootstrap` via data sources.
  Validate either layer with `terraform fmt -check && terraform validate` (run
  `terraform init` first; `1_app` needs the backend, so use `-backend=false` for
  an offline validate).
- CI/CD: `.github/workflows/deploy-app.yml` (app code → App Service via OIDC) and
  `.github/workflows/infra.yml` (`infra/1_app` Terraform plan/apply via OIDC,
  gated by the `production-infra` environment). No publish profile or client
  secret is stored — both use federated managed-identity credentials.

## Architecture (the big picture)

Blueprint-based Flask app. Dependency injection separates the **pure factory**
from the **composition root** — reading any one file is not enough:

- `app.py` — `create_app(config, org_store)` is a *pure factory*: it wires a
  Flask app purely from its injected dependencies and knows nothing about the
  environment or about testing. `build_app()` (the composition root, run at
  module import for `gunicorn app:app`) constructs the real `Config`, telemetry,
  and `CosmosOrgStore`, then calls `create_app`. Tests call `create_app` directly
  with their own `OrgStore`.
- `config.py` — the **only** module that reads `os.environ`. All configuration
  (including secrets, Cosmos, App Insights connection string) is read **once**
  into a `Config` object; `_require_env()` raises a clear startup error. Derived
  URLs are `@property`/methods, never rebuilt ad hoc.
- `models.py` — `Org` is a plain dataclass (a Cosmos document); the `slug` is its
  id/partition key. Slug handling lives in `Org.normalize_slug` /
  `Org.is_valid_slug`.
- `org_store.py` — `OrgStore` is the persistence **interface** (Protocol) the app
  depends on; `CosmosOrgStore` is the Cosmos DB for NoSQL implementation
  (passwordless via `DefaultAzureCredential`, connects lazily on first use). Get
  it in a request via `current_app.config["ORG_STORE"]`.
- `auth.py` — admin authentication/authorization via **App Service Easy Auth**.
  Easy Auth (configured to allow unauthenticated requests) signs the admin in at
  the platform level and injects claims as the `X-MS-CLIENT-PRINCIPAL` header;
  `admin_required` decodes it and checks for the Entra **app role**. Participants
  are never sent through this flow. `ADMIN_DEV_BYPASS=1` fakes an admin locally.
- `participants.py` — the public flow: GitHub OAuth (identity only) + `/join`,
  scoped to a single org `slug` looked up from the DB.
- `admin.py` — the Easy Auth-protected org-list CRUD plus the projectable QR
  page.
- `templates/` — server-rendered Jinja, all extending `base.html` (GitHub dark
  theme inline CSS).
- `infra/0_bootstrap/` — Terraform (azurerm) day-0 layer: the app resource group,
  the Terraform remote-state Storage Account/container, and the privileged GitHub
  OIDC infra identity (UMI + federated credential + RBAC). Local state, human-run.
- `infra/1_app/` — Terraform (azurerm + azuread) application layer: Linux App
  Service Plan/Web App (system-assigned identity), Cosmos DB (serverless, key auth
  disabled) + data-plane RBAC role assignment, Application Insights, the Entra app
  registration whose **admin** app role is wired into Easy Auth, and the
  least-privilege app-deploy OIDC identity. Remote state; RG + infra identity read
  from `0_bootstrap` via data sources.

### Three credentials, each at minimum privilege

This separation is the core security design — keep it intact:

1. **Entra ID app role** (via App Service Easy Auth) — authorizes the admin
   (CRUD UI only). The app holds no Entra client secret; it only reads the
   injected principal header and matches `ENTRA_ADMIN_ROLE`.
2. **GitHub OAuth App** — identifies the participant; requested `scope` is
   **empty** on purpose (we only need their login).
3. **GitHub classic PAT (`admin:org`)** — a single token, held in env
   (`GITHUB_INVITE_TOKEN`), used for **every** org invitation. No per-org secret
   is ever stored in the database. Invitations are only allowed for orgs that
   exist in the DB, so the broad PAT can't invite into an arbitrary org.

## Conventions specific to this codebase

- **Dependency injection, not environment/test branching:** the app factory
  receives its collaborators (config, `OrgStore`) as arguments. Application code
  must never branch on "am I in Azure/local/tests" or know that tests exist —
  wire concrete implementations in the composition root (`build_app`) and inject
  fakes from tests. Behaviour is driven by injected dependencies and `Config`
  values, not by sniffing the environment.
- **Config access in blueprints:** never read `os.environ` outside `config.py`.
  Inside a request, get config via the module-local `_config()` helper
  (`current_app.config["APP_CONFIG"]`) and the store via `current_app.config["ORG_STORE"]`.
- **GitHub API calls:** use the module-level shared `requests.Session`
  (connection pooling), always pass `timeout=HTTP_TIMEOUT` `(connect, read)`, and
  send the `Accept: application/vnd.github+json` and
  `X-GitHub-Api-Version: 2022-11-28` headers. Handle `requests.RequestException`
  and branch on status codes (e.g. 200/403/422) with user-facing flash messages.
- **CSRF on every state-changing POST:** enforced app-wide by **Flask-WTF**
  (`CSRFProtect`, initialised in `create_app`); forms render the hidden field via
  `{{ csrf_token() }}`. No manual token plumbing per route. The OAuth `state` is
  still validated manually with `secrets.compare_digest`. Don't disable CSRF for
  a new POST; add `{{ csrf_token() }}` to its form.
- **Logging & telemetry:** use a module-level `logger = logging.getLogger(__name__)`;
  log actions/outcomes at INFO, failures at WARNING. Never log secrets (tokens,
  client secrets) and keep PII (GitHub logins) to DEBUG — INFO logs use org
  `slug` + status only. `telemetry.configure_telemetry()` enables Azure Monitor
  (Application Insights) only when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set;
  it's a no-op locally. `configure_azure_monitor` auto-instruments Flask,
  `requests`, and the `logging` module, so plain `logger` calls reach App Insights.
  Flask's instrumentation patches the `flask.Flask` attribute, so `create_app`
  builds the app via `flask.Flask(__name__)` (resolved at call time, after
  `build_app` calls `configure_telemetry`) — not `from flask import Flask`, which
  would capture the un-instrumented class and drop incoming "requests" telemetry.
  Because `configure_azure_monitor` collects the **root** logger, the chatty
  Azure SDK loggers (esp. `azure.monitor.opentelemetry.exporter`'s own
  "Transmission succeeded…" and `azure.core` HTTP logs) would be re-exported as
  telemetry — a feedback loop that floods ingestion and drops the app's own
  logs. `app._quiet_noisy_loggers()` forces `_NOISY_LOGGERS` (azure*, urllib3,
  opentelemetry) to WARNING (re-applied after `configure_telemetry`); keep app
  loggers at INFO and never lower those noisy ones back down.
- **No persisted user data:** the participant flow keeps only what it needs in
  the signed session cookie (`user_login`, invite state) and discards the GitHub
  user token immediately after reading the login.
- **QR codes** are generated with `segno` (`segno.make(target, error="m")
  .svg_inline(...)`) and embedded inline in templates via `| safe`.
- **Templates** are server-rendered Jinja with inline CSS in a GitHub dark theme
  (see the `--bg/--card/--accent` CSS variables in `templates/`). Match this
  style for new pages rather than adding a CSS framework.
- **Cookies:** `SESSION_COOKIE_SECURE` is derived from whether `APP_BASE_URL` is
  HTTPS, so local `http://127.0.0.1` testing still works.
