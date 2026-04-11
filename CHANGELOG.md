# Changelog

All notable changes to PromptMatrix are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [0.2.1] — 2026-04-11

### Fixed
- **INSTALL-01**: `pip install -r requirements.txt` was impossible for all new users due to an irreconcilable version conflict between `fastapi==0.115.0` and `starlette>=0.49.1`. Resolved by upgrading to `fastapi>=0.135.0` which bundles `starlette 1.0.0`.
- **INSTALL-02**: `start.bat` and `start.sh` incorrectly aborted with "Dependency installation failed" even on successful installs because pip exits with code 1 when printing "upgrade available" notices. Fixed by upgrading pip first.
- **LINK-01**: All GitHub links in the landing page and source docs pointed to a 404 URL (`/PromptMatrix/PromptMatrix`). Corrected to the live repository (`/PromptMatrix/promptmatrix.github.io`).
- **ROUTE-01**: Vercel routes for `/register`, `/login`, `/reset-password`, and `/pm/*` were falling through to the static file handler and returning 404. Added explicit routes to forward them to FastAPI.
- `pyproject.toml`: synced dependency versions with `requirements.txt`; fixed project URLs.

### Security
- **CVE-2025-54121** (Moderate): starlette multipart parsing DoS — patched via `fastapi>=0.135.0`.
- **CVE-2025-62727** (High): starlette FileResponse O(n²) DoS via crafted Range headers — patched via `fastapi>=0.135.0` → `starlette 1.0.0`.

---

## [0.2.0] — 2026-04-06

### Added
- **Quick Approve** endpoint (`POST /api/v1/prompts/{id}/versions/{vid}/quick-approve`) — 1-click draft-to-live for local development. Returns 403 in production.
- **Writing Assist** (`POST /api/v1/prompts/assist`) — BYOK LLM assist for prompt generation, improvement, and critique. Supports all 5 LLM providers.
- **Feedback endpoint** (`POST /pm/serve/{key}/feedback`) — record real-world outcome telemetry (latency, tokens, success/failure) per served prompt.
- **Serve Events** (`serve_events` table) — telemetry logging for every `/pm/serve/` call. Tracks latency, cache hit, unfilled variables, tokens used.
- **Eval Results** (`eval_results` table) — persistent storage for LLM judge evaluation results.
- **Promotion Requests** (`promotion_requests` table) — formal audit trail for environment-to-environment prompt promotions.
- `eval_required` flag on environments — gate promotion until an eval passes.
- `target_model` and `target_provider` on prompt versions — per-version model targeting.
- `override_eval` flag on prompt versions — skip eval gate for specific versions.
- `is_active` flag on eval keys.
- `invited_by_id` on org members.
- `last_login_at` on users.
- `description` field on projects with uniqueness constraint `(org_id, name)`.
- `version` counter on prompts for optimistic locking.
- Full `PromptService` service layer with isolated, audited, testable workflow operations.
- Paginated approval queue (`GET /api/v1/approvals?limit=20&offset=0`).
- `AuditService` centralized audit logging.
- `AuthService` centralized authentication logic.
- `_MemoryCache` in-process TTL cache (5000-entry FIFO eviction, zero external deps).
- Rate limiting via in-memory sliding window (per API key, per minute).
- Security headers middleware: CSP, X-Frame-Options, X-Content-Type-Options, HSTS.
- `SECURITY.md`, `CODE_OF_CONDUCT.md` community health files.
- `.github/ISSUE_TEMPLATE/` bug and feature request templates.
- `.github/pull_request_template.md`.
- `pmx.py` CLI: push, pull, diff, list, eval, promote, status commands.
- Docker multi-stage build with non-root user execution.
- `start.sh` / `start.bat` auto-generate cryptographic keys on first run.
- Groq and Mistral LLM providers fully supported in eval and assist.

### Fixed
- **BUG-01**: Groq and Mistral provider configs now use the unified `PROVIDER_CONFIG` dict — previously broken with 400 errors.
- **BUG-02**: Variable substitution (`?vars=key=value`) no longer breaks on values containing commas.
- **BUG-03**: `list_prompts` uses a subquery count pattern — no longer loads all version content into memory.
- **BUG-04**: Audit log URL construction in the dashboard no longer produces malformed URLs without filters.
- **BUG-08**: `unfilled` variables are detected and returned in JSON mode serve responses.
- **BUG-10**: Approval queue is paginated with `total` count returned.
- `config.py` production validator now checks all four security conditions: encryption key present, JWT key not default, PostgreSQL URL, and key distinctness.
- `FeedbackIn` Pydantic model moved to top of `serve/router.py` (PEP-8 compliant).
- `prompt_cache_ttl_seconds` default aligned to 30s (was inconsistently 60 in code, 30 in docs).

### Security
- Import whitelist on workspace import: `approved`/`archived` status forced to `draft`.
- Production validators now block startup if JWT default key or SQLite is used in `APP_ENV=production`.
- AES-256-GCM encryption for stored eval keys. `ENCRYPTION_KEY` must be distinct from `JWT_SECRET_KEY`.

---

## [0.1.0] — 2026-03-23

### Added
- Initial public release.
- Core 10-table schema: organisations, users, org_members, projects, environments, api_keys, eval_keys, audit_logs, prompts, prompt_versions.
- FastAPI backend with full CRUD for prompts and versions.
- SQLite (local) and PostgreSQL (production) dual-mode support via `DATABASE_URL`.
- JWT authentication (access + refresh tokens, 60-min / 30-day).
- Prompt approval workflow: `draft → pending_review → approved → archived`.
- Rule-based eval engine (6 dimensions, zero external deps).
- LLM-as-judge eval (BYOK: Anthropic, OpenAI, Google).
- `/pm/serve/{key}` serve endpoint with variable substitution.
- API key management with SHA-256 hashing.
- AuditLog for all write operations.
- Alembic migrations with SQLite-compatible downgrade paths.
- `alembic upgrade head` auto-run in `start.sh` / `start.bat`.
- Local-first auto-seed: admin user + default project + 3 environments on first run.
- `/api/status` health endpoint.
- Dashboard served at `/dashboard` (vanilla JS, no build step).
- `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `LICENSE` (MIT).
- GitHub Actions CI: install → migrate → test.
- Dependabot for automated dependency updates.
