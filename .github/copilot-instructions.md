# Copilot instructions — QR Org Join

A small Flask app that lets people self-join a GitHub organization by scanning a
per-org QR code. An admin manages the list of joinable orgs through an
Entra-protected CRUD UI; participants scan a code, sign in with GitHub, and are
invited into that org. The app never administers members itself — invitation
acceptance, roles, and removals all happen on GitHub.com.

## Run, build, deploy

There is no automated test suite or linter configured; do not invent commands
for them. Validate changes by building the app factory (below).

- Smoke-test the factory without a server or Cosmos (inject a fake store from
  outside — the app has no test/env awareness):
  ```bash
  FLASK_SECRET_KEY=x APP_BASE_URL=http://127.0.0.1:8000 \
  COSMOS_ENDPOINT=https://dummy.documents.azure.com:443/ \
  GITHUB_CLIENT_ID=x GITHUB_CLIENT_SECRET=x \
  GITHUB_APP_ID=1 GITHUB_APP_PRIVATE_KEY=x GITHUB_WEBHOOK_SECRET=x \
  .venv/bin/python -c "import app; from config import Config; \
    a=app.create_app(Config(), object(), object()); print(sorted(str(r) for r in a.url_map.iter_rules()))"
  ```
  (`create_app(config, org_store, github_client)`; pass fakes for the store and
  the `GitHubClient` to exercise routes.) `app.py` exposes the WSGI callable
  `app` (so `gunicorn app:app` works). There is no local dev server.
- The venv (`.venv`) targets Python 3.12 (matching the Azure runtime); type
  hints use `from __future__ import annotations`. All config is via env vars,
  injected by App Service as app settings (Key Vault references for secrets).
  (The Azure deploy uses App Service's built-in Python runtime via Oryx.)
- Deploy: a **single** Terraform layer in `infra/`, run by a human locally with
  `az login` and **local state**. It provisions the resource group, a VNet with
  App Service regional integration, a **private** Cosmos DB (serverless) and Key
  Vault (both reached over private endpoints + private DNS zones), Application
  Insights, and the Entra Easy Auth app. App secrets live in Key Vault and are
  surfaced as `@Microsoft.KeyVault(...)` app-setting references resolved by the
  app's user-assigned identity. The vault denies public traffic except
  `operator_ip_cidr` so `terraform apply` can seed secrets. Validate offline with
  `terraform init && terraform fmt -check && terraform validate`.
- CI/CD: only `.github/workflows/deploy-app.yml` (app code → App Service via
  OIDC, using a Website-Contributor identity separate from `infra/`). Infra is
  applied by hand. No publish profile or client secret is stored.

## Architecture (the big picture)

Blueprint-based Flask app. Dependency injection separates the **pure factory**
from the **composition root** — reading any one file is not enough:

- `app.py` — `create_app(config, org_store, github_client)` is a *pure factory*:
  it wires a Flask app purely from its injected dependencies and knows nothing
  about the environment or about testing. `build_app()` (the composition root, run
  at module import for `gunicorn app:app`) constructs the real `Config`, telemetry,
  `CosmosOrgStore`, and `PyGithubClient`, then calls `create_app`. Tests call
  `create_app` directly with their own `OrgStore` and `GitHubClient`.
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
  are never sent through this flow.
- `participants.py` — the public flow: GitHub OAuth (identity only) + `/join`,
  scoped to a single org `slug` looked up from the DB. Uses the injected
  `GitHubClient` (`current_app.config["GITHUB"]`) for OAuth + invitations.
- `github_client.py` — `GitHubClient` **Protocol** + `PyGithubClient` (all GitHub
  access via **PyGithub**, one SDK): OAuth `ApplicationOAuth` for participant
  identity, and `Auth.AppAuth`→`GithubIntegration`→`AppInstallationAuth` for
  least-privilege per-org invitations (PyGithub mints/refreshes installation
  tokens). Injected via `current_app.config["GITHUB"]`.
- `webhooks.py` — `POST /webhooks/github`: HMAC-SHA256-verified (stdlib `hmac`,
  GitHub's `X-Hub-Signature-256`) `installation` handler that auto-onboards
  (`created`) / removes (`deleted`) orgs and records the installer login +
  timestamp on the `Org`. Public + `csrf.exempt`.
- `admin.py` — the Easy Auth-protected org console. Orgs are onboarded by the
  install webhook (no manual add/rename); the admin can manage each org's join
  passcode, check installation status, project a QR, and **Remove** a stale entry
  (escape hatch for a missed uninstall webhook). The list has client-side
  search / installer-filter / sort.
- `templates/` — server-rendered Jinja, all extending `base.html` (Microsoft
  Fluent / M365 Copilot inline CSS; shared styles + tokens live in `base.html`).
- `infra/` — a single Terraform layer (azurerm + azuread), local state, human-run
  with `az login`. Provisions: the resource group; a VNet with `snet-app`
  (delegated `Microsoft.Web/serverFarms`, for App Service regional VNet
  integration) and `snet-pe` (private endpoints); private DNS zones
  (`privatelink.documents.azure.com`, `privatelink.vaultcore.azure.net`) + VNet
  links; a **private** Cosmos DB (serverless, key auth disabled) + data-plane RBAC;
  a **private** Key Vault (RBAC-authorized, public traffic denied except
  `operator_ip_cidr`) holding all app secrets; private endpoints for Cosmos ("Sql")
  and Key Vault ("vault"); Application Insights; and the Entra app registration
  whose **admin** app role is wired into Easy Auth. The Web App uses a
  **user-assigned identity** (for both Cosmos data-plane and Key Vault reference
  resolution) and consumes secrets as `@Microsoft.KeyVault(...)` app settings.
  Files: `main.tf`, `networking.tf`, `keyvault.tf`, `entra.tf`, plus
  `variables.tf`/`outputs.tf`/`versions.tf`/`checks.tf`. Config is intentionally
  minimal — `location`, `resource_group_name`, `app_name`, plus the unavoidable
  credentials and `operator_ip_cidr`.

### Three credentials, each at minimum privilege

This separation is the core security design — keep it intact:

1. **Entra ID app role** (via App Service Easy Auth) — authorizes the admin
   (CRUD UI only). The app holds no Entra client secret; it only reads the
   injected principal header and matches `ENTRA_ADMIN_ROLE`.
2. **GitHub OAuth App** — identifies the participant; requested `scope` is
   **empty** on purpose (we only need their login).
3. **GitHub App (*Members* + *GitHub Copilot Business*: write)** — installed
   **per org** (not an owner), it mints short-lived per-org **installation
   tokens** to send invitations and best-effort assign the invitee a Copilot seat
   (`org.get_copilot().add_seats([login])`; failures never fail the invite).
   Credentials in env: `GITHUB_APP_ID`,
   `GITHUB_APP_PRIVATE_KEY` (PEM), `GITHUB_WEBHOOK_SECRET`. Invitations are only
   allowed for orgs in the DB, and the token is scoped to the single installed
   org — so it can't invite into an arbitrary org. Installing the app fires an
   `installation` webhook (`/webhooks/github`, HMAC-verified) that auto-onboards
   the org.

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
- **GitHub API calls:** go through the injected `GitHubClient`
  (`current_app.config["GITHUB"]`), backed by `PyGithubClient` in
  `github_client.py` — never raw `requests`. Handle `github.GithubException`
  (and subclasses `UnknownObjectException`, `RateLimitExceededException`),
  branching on `.status` with user-facing flash messages.
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
  it's a no-op when unset. `configure_azure_monitor` auto-instruments Flask,
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
  HTTPS.
