---
name: promptmatrix
description: Complete architectural knowledge for PromptMatrix. Load this before any task involving the codebase — architecture, data model, API design, business rules, deployment context, testing patterns, and known constraints. This is the single source of truth for the agent.
---

# PromptMatrix — Agent Architecture Skill

## What This System Is

PromptMatrix is a **prompt governance backend** for AI teams. The core problem it solves: prompts hardcoded in application code are ungoverned — no version history, no approval gate, no way for non-engineers to safely edit them, no audit trail.

PromptMatrix pulls every prompt into a governed registry. Non-engineers edit prompts in a dashboard. Engineers review a diff and approve. The approved content goes live in 10 seconds via a serve endpoint that agents call at runtime. No redeploy. Ever.

**The single most important endpoint in the entire system is `GET /pm/serve/{key}`.** Everything else — the registry, the approval workflow, the audit log — exists to serve that one endpoint correctly.

---

## Deployment Stack

```
Runtime:     Vercel (serverless Python functions)
Database:    Supabase (PostgreSQL via transaction pooler port 6543)
Cache:       Upstash Redis (HTTP-based, shared across Vercel instances)
Email:       Resend (100 emails/day free tier)
Frontend:    Static HTML files (promptmatrix-app.html, promptmatrix-landing.html)
```

**Critical Vercel constraint:** Each request may be a new Lambda process. There is no persistent in-memory state between requests. This means:
- `lru_cache` / in-memory dicts for caching = zero benefit, never warms up
- `asyncio.create_task` = killed when function returns, never runs
- All caching must use Upstash (external HTTP-based Redis)
- All background work must be `await`ed before the response returns

**Critical Supabase constraint:** Use port **6543** (Transaction pooler), NOT 5432 (direct connection). Transaction mode is stateless — one connection per request, released immediately. Port 5432 uses persistent sessions which break on serverless.

---

## File Structure

```
pm-v2/
├── main.py                          # FastAPI app entry point, CORS, router registration
├── vercel.json                      # Routes all requests to main.py
├── alembic.ini                      # Alembic config — reads DATABASE_URL from env
├── pytest.ini                       # Test config — testpaths=tests, asyncio_mode=auto
├── requirements.txt                 # All deps including pytest/pytest-asyncio
├── .env.example                     # All environment variables documented
│
├── app/
│   ├── config.py                    # Settings (pydantic-settings), production validation
│   ├── database.py                  # SQLAlchemy engine, SessionLocal, get_db, create_tables
│   ├── models.py                    # All SQLAlchemy models
│   │
│   ├── core/
│   │   ├── auth.py                  # JWT, password hashing, API key gen, AES-256-GCM
│   │   └── email.py                 # Resend templates — all async, timeout=5s, fail-open
│   │
│   ├── serve/
│   │   ├── cache.py                 # Upstash Redis cache + rate limiter
│   │   └── router.py               # GET /pm/serve/{key} — the hot path
│   │
│   └── api/v1/
│       ├── auth.py                  # /api/v1/auth/* — register, login, refresh, me
│       ├── prompts.py               # /api/v1/prompts/* — full CRUD + workflow
│       ├── approvals.py             # /api/v1/approvals — pending queue
│       ├── keys.py                  # /api/v1/keys/* — create, revoke, rotate
│       ├── projects.py              # /api/v1/projects — list with environments
│       ├── orgs.py                  # /api/v1/orgs/{id}/members — invite, remove
│       ├── audit.py                 # /api/v1/audit — filtered log
│       ├── evals.py                 # /api/v1/evals/* — LLM-as-judge + rule-based
│       └── webhooks.py             # /api/v1/webhooks/razorpay — payment events
│
├── migrations/
│   ├── env.py                       # Reads DATABASE_URL from app config
│   ├── script.py.mako               # Template for future --autogenerate migrations
│   └── versions/
│       └── 0001_initial_schema.py  # All 10 tables, SQLite/PostgreSQL dialect-aware
│
└── tests/
    ├── conftest.py                  # Fixtures, test DB, seed helpers, cache no-op patch
    ├── test_auth.py                 # 10 tests: register, login, refresh, JWT
    ├── test_config.py               # 8 tests: production validation rules
    ├── test_prompts.py              # 11 tests: state machine, rollback, archive
    ├── test_serve.py                # 14 tests: serve path, cache invalidation, rate limit
    └── test_keys.py                 # 6 tests: create, revoke, rotate lifecycle
```

---

## Data Model

### Hierarchy

```
Organisation (1)
  └── OrgMember (many) ← User (many)
  └── Project (1 per org, auto-created on register)
        └── Environment (3 auto-created: production, staging, development)
              ├── ApiKey (many)
              └── Prompt (many)
                    └── PromptVersion (many)
                          └── EvalKey (per-org, not per-prompt)
AuditLog (per-org, append-only)
```

### Key design decisions in models.py

**Circular FK between Prompt and PromptVersion:**
- `Prompt.live_version_id → PromptVersion.id` — which version is currently live
- `PromptVersion.prompt_id → Prompt.id` — which prompt this version belongs to
- Resolved with `use_alter=True` on `live_version_id` FK and `post_update=True` on the relationship
- In Alembic migration: tables are created first without the circular FK, then `op.create_foreign_key` adds it. SQLite skips this (no ALTER TABLE constraint support) but works because SQLite doesn't enforce FKs by default.

**PromptVersion statuses (the state machine):**
```
draft → pending_review → approved → archived
                      ↘ rejected
```
- `draft`: created but not submitted for review
- `pending_review`: submitted, waiting for engineer approval
- `approved`: currently live (or was live, now archived)
- `rejected`: rejected by engineer with a reason
- `archived`: was live, superseded by a newer approved version

**When a version is approved:**
1. The previous `live_version_id` version status → `archived`
2. New version status → `approved`
3. `Prompt.live_version_id` → new version ID
4. Cache invalidated immediately (`await invalidate_prompt_cache(env.id, prompt.key)`)

**Rollback:** Creates a new approved version with the target version's content. Never mutates history. The new version gets the next version number. Rollback is always `await`ed and cache is invalidated.

**AuditLog column `extra`:** Named `extra` not `metadata` — `metadata` is a reserved name in SQLAlchemy's declarative base.

### All 10 database tables

| Table | Purpose |
|-------|---------|
| `organisations` | Workspace/company entity |
| `users` | Individual accounts (email + bcrypt hash) |
| `org_members` | User ↔ Org with role (viewer/editor/engineer/admin/owner) |
| `projects` | Container for environments (1 per org currently) |
| `environments` | production / staging / development per project |
| `prompts` | Named prompt keys within an environment |
| `prompt_versions` | Content snapshots with status and approval metadata |
| `api_keys` | Serve endpoint credentials (hash stored, never plaintext) |
| `eval_keys` | Team LLM API keys (AES-256-GCM encrypted) |
| `audit_logs` | Append-only event log per org |

---

## The Serve Path — Most Critical Code

`app/serve/router.py` — `GET /pm/serve/{prompt_key:path}`

This is the only endpoint agents call. It is on the hot path and must never fail unexpectedly.

**Exact execution order:**
1. Extract `Authorization: Bearer pm_live_xxx` header — 401 if missing
2. Hash the key: `hashlib.sha256(raw_key.encode()).hexdigest()`
3. Check Upstash cache for key data (`key:{hash}`) — returns `{environment_id, env_name, org_id, plan}`
4. Cache miss: query `api_keys` table, then `environments`, `projects`, `organisations`. **Two separate queries** for project and org — never chain `.first().attribute` (crashes if `.first()` returns None)
5. Update `api_key.last_used_at` and commit
6. **Rate limit check** using Upstash INCR sliding window (keyed per hash, per 60s bucket). Returns 429 with `Retry-After: 60` if exceeded. **Fails open** — Redis error = allow
7. Check Upstash cache for prompt content (`prompt:{env_id}:{key}`)
8. Cache miss: query `prompts` then `prompt_versions` WHERE `id = live_version_id AND status = 'approved'`
9. Variable substitution: `?vars=name=John,tone=formal` replaces `{{name}}` and `{{tone}}`
10. Return `PlainTextResponse` (default) or JSON dict if `?format=json`

**Why `_db()` instead of `Depends(get_db)`:**
The serve router uses manual `SessionLocal()` instead of FastAPI's dependency injection. This avoids the per-request overhead of the DI system on the most called endpoint in the app. The DB session is always closed in a `finally` block.

**Session pattern in serve router:**
```python
db = _db()
try:
    # queries here
    db.commit()
finally:
    db.close()
```
Never use `with` statement — the `try/finally` is intentional.

---

## Cache Architecture (`app/serve/cache.py`)

Two implementations, selected at module load time:

```python
_cache = _UpstashCache(url, token)  # if UPSTASH_REDIS_REST_URL is set
_cache = _NoopCache()               # otherwise — always returns None / no-ops
```

**`_UpstashCache`:** Upstash REST API (HTTP GET). No persistent connection. Every operation is an async `httpx` call with `timeout=2.0`. Safe for serverless.

**`_NoopCache`:** Returns `None` on every get, no-ops on set/delete. Application works correctly, just reads DB on every request.

**Cache key format:**
- API key lookup: `key:{sha256_hash}` — TTL 300s (5 min)
- Prompt content: `prompt:{environment_id}:{prompt_key}` — TTL 30s
- Rate limit counter: `rl:{sha256_hash}:{unix_minute_bucket}` — TTL 120s

**Rate limiting (`check_rate_limit`):**
- Uses Upstash `INCR` command on a per-minute bucket key
- `EXPIRE` set to 120s only on the first request (count == 1) to save one round-trip
- Returns `(allowed: bool, count: int, limit: int)`
- Always returns `(True, 0, rpm_limit)` if `_NoopCache` is active
- Always returns `(True, 0, rpm_limit)` on any Redis exception (fail-open)

**Cache invalidation:**
Called `await invalidate_prompt_cache(env.id, prompt.key)` after:
- Version approved
- Version rolled back
- Prompt deleted

Called `await invalidate_key_cache(key_hash)` after:
- Key revoked
- Key rotated (old key hash)

All cache calls are `await`ed — never `asyncio.create_task`.

---

## Authentication System (`app/core/auth.py`)

### JWT tokens

Both access and refresh tokens carry `org_id` in the payload:
```python
{"sub": user_id, "org": org_id, "type": "access"|"refresh", "exp": ..., "iat": ...}
```

This is critical — `get_current_user_and_org` reads `org_id` from the token to look up the `OrgMember` row. If `org_id` is missing from a refresh token, the next access token will have no org context and every protected route will return 403.

### API key format

`pm_live_{secrets.token_urlsafe(32)}` for production
`pm_stg_{...}` for staging
`pm_dev_{...}` for development

The full key is returned **once** on creation. Never stored. The `key_hash` (SHA-256 hex) is stored and used for all lookups. The `key_prefix` (first 16 chars) is stored for UI display only.

### Role hierarchy

```python
ROLE_HIERARCHY = {"viewer": 0, "editor": 1, "engineer": 2, "admin": 3, "owner": 4}
```

`require_role(member, min_role)` raises 403 if `member.role` level < `min_role` level.

| Action | Minimum role |
|--------|-------------|
| Read prompts, view registry | viewer |
| Create/edit prompts, propose versions | editor |
| Approve/reject versions, create API keys, rollback | engineer |
| Invite/remove members | admin |
| Everything + billing | owner |

### AES-256-GCM encryption for eval keys

Used for team LLM API keys stored in `eval_keys` table:
```python
key_material = settings.encryption_key or settings.jwt_secret_key
encryption_key_bytes = hashlib.sha256(key_material.encode()).digest()
```

`ENCRYPTION_KEY` must be **different** from `JWT_SECRET_KEY`. The production validator enforces this. Rotating one must never break the other. If `cryptography` package is missing, raises `RuntimeError` — no silent fallback to base64.

---

## Email System (`app/core/email.py`)

All email functions are `async def` and use `httpx.AsyncClient(timeout=5.0)`.

**Rules:**
- All email calls in route handlers are `await`ed directly — never `asyncio.create_task`
- `await send_*()` calls are wrapped in `try/except` — email failure never raises
- If `RESEND_API_KEY` is empty, emails are logged to stdout and skipped
- `timeout=5.0` — adds max 5s to the response time when emails are sent

**Available templates:**
- `send_welcome(email, org_name, plan)` — on register
- `send_approval_needed(approver_email, requester_name, prompt_key, version_num, env_name, note, dashboard_url)` — on submit for review, sent to all engineers/admins/owners in org
- `send_version_approved(requester_email, approver_name, prompt_key, version_num, env_name)` — on approve
- `send_version_rejected(requester_email, reviewer_name, prompt_key, version_num, reason, dashboard_url)` — on reject
- `send_invite(invitee_email, inviter_name, org_name, role, temp_password)` — on new member invite
- `send_eval_failed(user_email, prompt_key, version_num, score, threshold, issues)` — on failed eval

---

## Config and Production Validation (`app/config.py`)

`@model_validator(mode="after")` runs on every `Settings()` instantiation when `APP_ENV=production`:

| Check | Error message |
|-------|--------------|
| `JWT_SECRET_KEY` is default value | "JWT_SECRET_KEY must be set" |
| `ENCRYPTION_KEY` is empty | "ENCRYPTION_KEY must be set" |
| `ENCRYPTION_KEY == JWT_SECRET_KEY` | "must be different values" |
| `DATABASE_URL` doesn't start with `postgresql` | "must be a PostgreSQL URL" |

In development, none of these apply — defaults work fine.

`get_settings()` is `@lru_cache()` — called once, result cached for the process lifetime. On Vercel, this means once per cold start (which may be every request). To mutate settings in tests, call `get_settings.cache_clear()` then reset env vars.

---

## Database Layer (`app/database.py`)

```python
_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs = {"connect_args": {"check_same_thread": False}} if _is_sqlite else {
    "pool_size": 2,
    "max_overflow": 5,
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
```

`pool_size` and `max_overflow` are NOT passed to SQLite — SQLite doesn't support these and raises an error. PostgreSQL gets a small pool because Supabase's transaction pooler handles the actual connection pooling on its side.

`pool_pre_ping=True` — drops stale connections before use. Important because Supabase free tier pauses after 7 days of inactivity. First request after a pause gets a stale connection; `pool_pre_ping` detects this and retries with a fresh one.

---

## Migrations (Alembic)

**Commands:**
```bash
alembic upgrade head       # apply all pending migrations
alembic downgrade -1       # roll back one migration
alembic current            # show current migration version
alembic revision --autogenerate -m "describe change"  # generate migration from model diff
```

**env.py reads `DATABASE_URL` from the app config** — never hardcoded in `alembic.ini`.

**When adding a new model field:**
1. Add column to the model in `app/models.py`
2. Run `alembic revision --autogenerate -m "add field_name to table_name"`
3. Review the generated file in `migrations/versions/`
4. Run `alembic upgrade head`
5. Commit both the model change and the migration file together

**Never use `create_tables()` to evolve a live schema.** `create_all()` only creates tables that don't exist — it never adds columns to existing tables. On a live Supabase instance with real data, schema changes must go through Alembic.

**Current migration:** `0001_initial_schema.py` — creates all 10 tables. This is the baseline. All future schema changes get new migration files.

---

## Testing (`tests/`)

**Test database:** SQLite in-memory (`sqlite:///./test_pm.db`), created fresh per session, cleaned between tests.

**conftest.py provides:**

```python
# Fixtures
client    # TestClient with DB override + NoopCache
db        # Raw SQLAlchemy session

# Seed helpers
seed_org_user(db, email, role, plan)
    # → (org, user, member, project, env)

seed_approved_prompt(db, env_id, user_id, key, content)
    # → (prompt, version) — live_version_id set

seed_api_key(db, env_id, name)
    # → (full_key_string, ApiKey row)

auth_headers(client, email, password)
    # → {"Authorization": "Bearer <token>"}
```

**Cache is patched in tests:** `cache_module._cache = _NoopCache()` — no Upstash credentials needed. Tests run against real DB logic.

**Running tests:**
```bash
pytest                     # all 51 tests
pytest tests/test_serve.py # specific file
pytest -k "rollback"       # specific test name pattern
pytest -v --tb=long        # verbose with full tracebacks
```

**51 tests total:**
- `test_auth.py` — 10 tests
- `test_config.py` — 8 tests
- `test_prompts.py` — 11 tests (state machine, rollback, archive, approval queue)
- `test_serve.py` — 14 tests (serve path, cache invalidation on approve, rate limit)
- `test_keys.py` — 6 tests (lifecycle, prefix format)

---

## All API Endpoints

### Auth — `/api/v1/auth`
| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/register` | None | Creates org + 3 environments automatically |
| POST | `/login` | None | Returns access + refresh tokens |
| POST | `/refresh` | None | Body: `{refresh_token}` — preserves org_id |
| GET | `/me` | Bearer | Returns user + active_org |

### Prompts — `/api/v1/prompts`
| Method | Path | Min Role | Notes |
|--------|------|----------|-------|
| GET | `?environment_id=` | viewer | joinedload prevents N+1 |
| POST | `` | editor | Key must match `^[a-z0-9._\-]{1,200}$` |
| GET | `/{id}` | viewer | Returns prompt + all versions |
| POST | `/{id}/versions` | editor | IntegrityError retry loop (3 attempts) |
| POST | `/{id}/versions/{vid}/submit` | editor | draft → pending_review |
| POST | `/{id}/versions/{vid}/approve` | engineer | pending_review → approved, invalidates cache |
| POST | `/{id}/versions/{vid}/reject` | engineer | → rejected |
| POST | `/{id}/versions/{vid}/rollback` | engineer | Creates new approved version |
| DELETE | `/{id}` | admin | Also invalidates cache |

### Other endpoints
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/approvals` | Pending versions across all org environments |
| GET/POST/DELETE | `/api/v1/keys` | API key lifecycle |
| POST | `/api/v1/keys/{id}/rotate` | Invalidates old key cache |
| GET | `/api/v1/projects` | Projects + environments list |
| GET/POST/DELETE | `/api/v1/orgs/{id}/members` | Team management |
| GET | `/api/v1/audit` | Filtered by `?resource_type=` |
| POST | `/api/v1/evals/run` | LLM-as-judge or rule-based |
| GET/POST/DELETE | `/api/v1/evals/keys` | Encrypted team LLM keys |
| POST | `/api/v1/webhooks/razorpay` | Payment → plan upgrade |
| GET | `/pm/serve/{key:path}` | The serve endpoint — no auth required in path |
| GET | `/api/status` | Health check |

---

## Environment Variables

| Variable | Required in prod | Default | Notes |
|----------|-----------------|---------|-------|
| `DATABASE_URL` | ✓ | `sqlite:///./promptmatrix.db` | Must be PostgreSQL in production (port 6543) |
| `JWT_SECRET_KEY` | ✓ | `dev-secret-change-in-production` | Must not be default in production |
| `JWT_ALGORITHM` | | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | | `60` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | | `30` | |
| `ENCRYPTION_KEY` | ✓ | `""` | Must differ from JWT_SECRET_KEY |
| `APP_ENV` | ✓ | `development` | Set to `production` on Vercel |
| `APP_URL` | | `http://localhost:8000` | Your Vercel URL |
| `FRONTEND_URL` | | `http://localhost:3000` | Your app HTML URL |
| `DEBUG` | | `False` | Never True in production |
| `RESEND_API_KEY` | | `""` | Empty = emails skipped |
| `FROM_EMAIL` | | `noreply@promptmatrix.io` | |
| `UPSTASH_REDIS_REST_URL` | | `""` | Empty = NoopCache |
| `UPSTASH_REDIS_REST_TOKEN` | | `""` | Empty = NoopCache |
| `RAZORPAY_KEY_ID` | | `""` | For payment webhooks |
| `RAZORPAY_WEBHOOK_SECRET` | | `""` | |
| `PROMPT_CACHE_TTL_SECONDS` | | `30` | |
| `API_KEY_CACHE_TTL_SECONDS` | | `300` | |
| `SERVE_RATE_LIMIT_RPM` | | `600` | Set 0 to disable |

---

## Business Logic Rules

### Version numbering
`_next_version_num()` queries `MAX(version_num)` for the prompt and returns +1. Wrapped in `IntegrityError` retry loop (3 attempts) for race condition safety on PostgreSQL.

### Prompt key format
Enforced by Pydantic `@field_validator`:
```
^[a-z0-9._\-]{1,200}$
```
Lowercase only. Alphanumeric, dots, dashes, underscores. Max 200 chars. Keys like `assistant.system`, `agent-briefing`, `email_composer_v2` are valid. `UPPERCASE`, `has spaces`, `slash/key` are rejected with 422.

### Variable substitution in prompts
`{{variable_name}}` syntax. Passed via `?vars=name=John,tone=formal` query param. Simple string replace — no conditionals, no loops. Unmatched variables stay as `{{variable_name}}` in the output.

### Workspace seeding on register
Every new organisation gets:
- 1 Project (`Default Project`)
- 3 Environments: `production` (protected, threshold 7.0), `staging` (protected, threshold 6.0), `development` (open, threshold 0.0)

### Razorpay webhook → plan upgrade
The webhook reads `payment.notes.org_id` to find which org to upgrade. The payment link must include `org_id` as a note. Plan changes from `free` → `founding`. The upgrade is logged to `audit_logs`.

### Audit log actions
Every significant state change writes to `audit_logs`. Key action strings:
- `org.created`, `auth.login`
- `prompt.created`, `prompt.deleted`
- `version.created`, `version.submitted`, `version.approved`, `version.rejected`, `version.rollback`
- `key.created`, `key.revoked`, `key.rotated`
- `member.invited`, `member.invited_new`, `member.removed`
- `eval.run`
- `org.plan_upgraded`

---

## Known Constraints and Non-Obvious Decisions

**Do not add in-memory caching.** Reviewed and rejected three times. On Vercel serverless, `lru_cache` and Python dicts are destroyed after each request. The reviewer who suggested it had persistent process environments in mind (Railway, fly.io). On Vercel it provides zero benefit and creates false latency expectations in comments.

**Do not add `asyncio.create_task`.** Vercel kills the function after the response is returned. Any task created via `create_task` is silently dropped. All async work must be `await`ed before the response is built.

**SQLite pool_size:** SQLite does not accept `pool_size` or `max_overflow` kwargs. The `_engine_kwargs` dict is conditionally built based on `_is_sqlite` to avoid this.

**`metadata` column name is reserved.** SQLAlchemy's `DeclarativeBase` uses `metadata` internally. The audit log column is named `extra` not `metadata`. This applies to any future model additions.

**Email sent before response:** In routes that send email (submit, approve, reject, invite, register), the `await send_*()` call happens before `return`. This adds ~50-200ms to those responses. Acceptable at current scale. If it becomes a problem, Upstash QStash is the correct solution — not `asyncio.create_task`.

**Single org per user (currently).** `/auth/login` returns the first `OrgMember` row for the user. Multi-org switching is not implemented. The JWT carries one `org_id`. This is a known simplification.

**Outbound webhooks are not implemented.** The `webhooks.py` file handles inbound Razorpay payments only. Customer-facing outbound webhooks (notify when version approved, etc.) are on the roadmap but the delivery worker does not exist yet.

---

## How to Make Schema Changes

1. Edit `app/models.py` — add column, table, or relationship
2. Run `alembic revision --autogenerate -m "short description"`
3. Open the generated file in `migrations/versions/` and review — autogenerate is not always perfect, especially for circular FKs
4. For circular FKs, add the `_is_sqlite()` guard pattern from `0001_initial_schema.py`
5. Run `alembic upgrade head`
6. If tests break, check conftest.py `_clean_db` — it deletes in dependency order and may need updating for new tables
7. Commit both the model file and the migration file together

---

## How to Add a New API Route

1. Find the relevant router file in `app/api/v1/`
2. Follow the existing pattern: `@router.METHOD("/path")`, `async def name(auth=Depends(get_current_user_and_org), db=Depends(get_db))`
3. Call `require_role(member, "minimum_role")` immediately after unpacking auth
4. Add an `AuditLog` entry for any state-changing action
5. If the action affects a live prompt or API key, call the appropriate `await invalidate_*_cache(...)` before returning
6. If sending email, wrap in `try/except`, use `await`
7. Register the router in `main.py` if it's a new file
8. Write tests in the corresponding `tests/test_*.py` file using the seed helpers from conftest.py

---

## How to Run Locally

```bash
# Install deps
pip install -r requirements.txt

# Create .env from example
cp .env.example .env
# Edit .env — minimum for local: DATABASE_URL (sqlite default works), JWT_SECRET_KEY, ENCRYPTION_KEY

# Run migrations (creates SQLite DB)
alembic upgrade head

# Run tests
pytest

# Start dev server
uvicorn main:app --reload --port 8000

# API docs (dev only)
open http://localhost:8000/docs
```

---

## Deployment Checklist

Before deploying to Vercel:

- [ ] `alembic upgrade head` run against Supabase (port 6543)
- [ ] All env vars set in Vercel dashboard
- [ ] `JWT_SECRET_KEY` is a fresh `secrets.token_hex(32)` value
- [ ] `ENCRYPTION_KEY` is a different fresh `secrets.token_hex(32)` value
- [ ] `APP_ENV=production` in Vercel env vars
- [ ] `DATABASE_URL` uses port 6543 not 5432
- [ ] `pytest` passes locally
- [ ] `curl https://your-project.vercel.app/api/status` returns `"env": "production"`
- [ ] `const API = 'https://...'` updated in `promptmatrix-app.html`

---

## Free Tier Limits

| Service | Limit | Behaviour at limit |
|---------|-------|--------------------|
| Supabase | 500MB storage, 2GB bandwidth | Upgrade required |
| Supabase (free) | Pauses after 7 days inactivity | First request after pause: 10-30s cold start. `pool_pre_ping=True` handles stale connections gracefully |
| Vercel | 100k function invocations/day | Throttled |
| Upstash | 10k commands/day (~5k serve requests) | Falls back to `_NoopCache` — app continues working |
| Resend | 100 emails/day | Emails fail silently — app continues working |

