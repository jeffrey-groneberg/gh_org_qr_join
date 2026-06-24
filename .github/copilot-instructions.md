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
- Smoke-test the factory without a server (used to validate changes here):
  ```bash
  FLASK_SECRET_KEY=x APP_BASE_URL=http://127.0.0.1:8000 DATABASE_URL=sqlite:///:memory: \
  GITHUB_CLIENT_ID=x GITHUB_CLIENT_SECRET=x GITHUB_INVITE_TOKEN=x ADMIN_DEV_BYPASS=1 \
  python -c "import app; print([str(r) for r in app.app.url_map.iter_rules()])"
  ```
- The venv (`.venv`) targets Python 3.9; type hints use `from __future__ import
  annotations` so 3.10+ syntax (`str | None`) is fine.
- Container: `Dockerfile` runs `gunicorn --bind 0.0.0.0:${PORT} app:app` as a
  non-root user — **local dev / portability only**. The Azure deploy uses App
  Service's built-in Python runtime (Oryx), not this image. All config is via
  env vars — see `.env.example`.
- Deploy: Terraform in `infra/` provisions Azure App Service + Entra Easy Auth.
  Validate IaC with `cd infra && terraform fmt -check && terraform init -backend=false && terraform validate`.
  SQLite must live on the persistent `/home` volume (the Terraform sets
  `DATABASE_URL=sqlite:////home/data/qr_org_join.db`).

## Architecture (the big picture)

Blueprint-based Flask app assembled by an application factory. Reading any one
file is not enough — the wiring is split deliberately:

- `app.py` — `create_app()` factory: builds `Config`, stores it on
  `app.config["APP_CONFIG"]`, initializes extensions, registers blueprints, runs
  `db.create_all()`, and is the WSGI entry point.
- `config.py` — all configuration is read **once** from the environment into a
  `Config` object. `_require_env()` raises a clear startup error for missing
  vars. Derived URLs (redirect URIs, per-org join URL) are `@property`/methods on
  `Config`, never rebuilt ad hoc.
- `extensions.py` — shared, unbound extension singletons (`db`, `oauth`) that the
  factory binds with `init_app`. Import these here, never construct new ones.
- `models.py` — SQLAlchemy `Org` model. Stores only non-secret metadata
  (`slug`, `display_name`, `member_role`). Slug handling lives in
  `Org.normalize_slug` / `Org.is_valid_slug`.
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
- `infra/` — Terraform (azurerm + azuread) for the Azure deployment: resource
  group, Linux App Service Plan/Web App, app settings, and the Entra app
  registration whose **admin** app role is wired into Easy Auth.

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

- **Config access in blueprints:** never read `os.environ` outside `config.py`.
  Inside a request, get config via the module-local `_config()` helper
  (`current_app.config["APP_CONFIG"]`).
- **GitHub API calls:** use the module-level shared `requests.Session`
  (connection pooling), always pass `timeout=HTTP_TIMEOUT` `(connect, read)`, and
  send the `Accept: application/vnd.github+json` and
  `X-GitHub-Api-Version: 2022-11-28` headers. Handle `requests.RequestException`
  and branch on status codes (e.g. 200/403/422) with user-facing flash messages.
- **CSRF on every state-changing POST:** a per-session token
  (`secrets.token_urlsafe`) is compared with `secrets.compare_digest` and the
  request is `abort(400)`ed on mismatch. OAuth `state` is validated the same way.
  Do not add a POST without this check.
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
