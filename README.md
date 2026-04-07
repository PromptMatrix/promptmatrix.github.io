<div align="center">

  <img src="PromptMatrix.webp" alt="PromptMatrix" width="100%">

  <h1>⬡ PromptMatrix</h1>
  <h3>The Governance Engine for AI Systems</h3>

  <p>
    <b>Stop hardcoding your LLM prompts. Start governing them.</b>
  </p>

  <p>
    <a href="https://github.com/jachinsaikiasonowal/promptmatrix/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License" /></a>
    <a href="https://github.com/jachinsaikiasonowal/promptmatrix/releases"><img src="https://img.shields.io/github/v/release/PromptMatrix/promptmatrix.github.io?label=version" alt="Version" /></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" /></a>
    <img src="https://img.shields.io/badge/SQLite-local--first-orange.svg" alt="Local-first SQLite" />
    <a href="https://github.com/jachinsaikiasonowal/promptmatrix/actions"><img src="https://github.com/jachinsaikiasonowal/promptmatrix/actions/workflows/test.yml/badge.svg" alt="CI" /></a>
  </p>

  <p>
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-features">Features</a> •
    <a href="#-deployment-models">Deployment Models</a> •
    <a href="#-manual-installation">Manual Installation</a> •
    <a href="https://github.com/jachinsaikiasonowal/promptmatrix/blob/main/LICENSE">MIT License</a>
  </p>
</div>

---

**PromptMatrix** is high-performance, open-source infrastructure for AI engineering teams. It centralizes your agent prompts into a version-controlled, auditable, and evaluated registry — enabling instant updates via sub-10ms APIs without ever redeploying your codebase.

---

## ⚡️ The Core Problem

If you're building sophisticated AI agents, copilots, or internal workflows, your system prompts are currently trapped as raw strings in your repository.

When a prompt fails in production, you have to submit a PR, run CI/CD, and redeploy your entire application just to change a system instruction. **PromptMatrix fixes this.**

```python
# ❌ BEFORE: Hardcoded, ungoverned, invisible to product teams
SYSTEM_PROMPT = "You are an elite AGI-level operator. Always respond in JSON..."
agent.run(SYSTEM_PROMPT)

# ✅ AFTER: Governed, evaluated, instantly updatable
system_prompt = requests.get(
    "http://localhost:8000/pm/serve/agent.architect",
    headers={"Authorization": "Bearer pm_live_xxx"}
).text
agent.run(system_prompt)
```

---

## ✨ Features

*   **⏱️ Zero-Downtime Hot Swaps:** Update your LLM instructions in real time. Changes propagate in milliseconds.
*   **⏪ Immutable Version History:** 1-click rollbacks for broken prompts. Never lose a historical state.
*   **⚖️ Built-in LLM-As-Judge Evals:** Natively test your prompts against Anthropic, OpenAI, Google, Groq, or Mistral before deploying.
*   **🛡️ Cryptographic Security:** Eval API keys are AES-256-GCM encrypted. Integration keys are SHA-256 hashed — never stored in plaintext.
*   **🔌 Universal Serve API:** Low-latency `GET /pm/serve/{key}` with in-memory caching, variable substitution, and JSON/text output modes.
*   **📊 Visual Dashboard:** Full governance UI at `http://localhost:8000/dashboard` — vanilla JavaScript, no build step required.
*   **🔒 Zero-Dependency Eval:** Rule-based eval engine scores across 6 dimensions with zero external dependencies — works completely offline.
*   **⌨️ Full CLI:** `pmx.py` for push, pull, diff, list, eval, and promote from the terminal.
*   **🐳 Docker Ready:** Multi-stage optimized container image with non-root user execution.
*   **📱 PWA Support:** Dashboard is installable as a Progressive Web App for desktop-like local access.

---

## 🆕 Release v0.2.0: Zero-Trust Architecture Update

We have heavily fortified the system for production-ready, zero-trust deployments:
*   **IDOR Protections:** Enforced strict Multi-Tenant schemas guaranteeing prompt and workspace isolation.
*   **Security Headers:** Natively integrated `Referrer-Policy` and `Permissions-Policy` in the Security Middleware.
*   **JWT Integrity:** Pinned symmetric signing algorithms to mitigate CVE-2024-33663 algorithm confusion.
*   **Strict Pagination:** Data endpoints now cap payloads strictly (e.g., limit=100) protecting against DDOS vector payload expansions.

---

## 🚀 Quick Start

PromptMatrix runs purely on SQLite with zero external database dependencies.

**Step 1:** Download the latest `.zip` from the [GitHub Releases](https://github.com/jachinsaikiasonowal/promptmatrix/releases) page and extract it.

**Step 2:** Run the startup script for your system:

### Windows
Double-click **`start.bat`** — it handles venv creation, dependencies, secret generation, and database migrations automatically.

### Linux / macOS
```bash
chmod +x start.sh
./start.sh
```

### Docker (Recommended for Servers)
```bash
docker compose up -d
```

**Access the Visual Governance Dashboard at:** `http://localhost:8000/dashboard`

---

## 🛠 Manual Installation

```bash
git clone https://github.com/jachinsaikiasonowal/promptmatrix.git
cd promptmatrix

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env      # Auto-generates secure keys on first run
alembic upgrade head

uvicorn main:app --reload --port 8000
```

---

## 📦 Repository Structure

```
PromptMatrix/
├── app/
│   ├── api/v1/          # FastAPI route handlers (auth, prompts, keys, evals, approvals, etc.)
│   ├── core/            # Auth logic, policy scanner, email stubs (disabled in local mode)
│   ├── serve/           # Low-latency prompt serving router + in-memory cache
│   ├── services/        # Business logic: PromptService, AuthService, AuditService
│   ├── config.py        # Pydantic settings (reads from .env)
│   ├── database.py      # SQLAlchemy session + SQLite/PostgreSQL engine
│   └── models.py        # ORM models (14 tables)
├── migrations/
│   └── versions/        # Alembic migration files (upgrades + downgrades)
├── tests/               # pytest test suite
├── dashboard.html       # Governance dashboard UI (vanilla JavaScript — no build step)
├── index.html           # Landing page
├── main.py              # FastAPI application entry point
├── pmx.py               # CLI: push, pull, diff, list, eval, promote
├── Dockerfile           # Multi-stage optimized container image (non-root)
├── docker-compose.yml   # Production-ready compose configuration
├── start.sh             # One-click setup for Linux/macOS
├── start.bat            # One-click setup for Windows
├── .env.example         # Configuration template (no secrets)
├── requirements.txt     # Python dependencies (no cloud services required)
└── alembic.ini          # Alembic configuration
```

---

## 🚀 Deployment Models

### 🏠 Local / Self-Hosted (This Repository)

- **Single-user, fully autonomous deployment**
- SQLite database — zero external dependencies
- Perfect for individual developers managing prompts locally
- 100% open source — MIT licensed
- Instant setup: run `./start.sh` or `start.bat`
- Login screen is skipped in development mode — dashboard opens directly

### ☁️ Team / Production (Self-Hosted PostgreSQL)

Switch to PostgreSQL for team deployments:

1. Set `DATABASE_URL=postgresql://user:password@host:5432/promptmatrix` in `.env`
2. Set `APP_ENV=production` to enable the login screen and security validators
3. Uncomment `psycopg2-binary` in `requirements.txt`
4. Run `alembic upgrade head` to apply migrations

> For multi-user team collaboration with RBAC, managed hosting, and advanced workflow features — see the [Cloud version](https://promptmatrix.io).

---

## ⌨️ CLI (`pmx.py`)

```bash
python pmx.py status                                         # Server health + version
python pmx.py list                                           # List all prompts
python pmx.py push agent.system ./prompt.txt                 # Push + auto-approve (dev mode)
python pmx.py pull agent.system ./out.txt                    # Pull live prompt to file
python pmx.py diff agent.system ./prompt.txt                 # Unified diff local vs live
python pmx.py eval agent.system ./prompt.txt --type rule_based  # Score offline (no API key)
python pmx.py promote agent.system production                # Promote to another environment
```

### CI/CD Integration

```yaml
# .github/workflows/eval_prompts.yml
- name: Evaluate prompts
  run: python pmx.py eval agent.system ./prompts/agent.txt --type rule_based
```

---

## 🧪 Running Tests

```bash
source venv/bin/activate  # Windows: venv\Scripts\activate
pytest -v
```

The test suite uses an in-memory SQLite database. No external services required.

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.
Bug reports and feature requests go in [Issues](https://github.com/jachinsaikiasonowal/promptmatrix/issues).

---

## 🔒 Security

Found a vulnerability? **Do not open a public issue.**
See [SECURITY.md](SECURITY.md) for our responsible disclosure policy.

---

## 📄 License

MIT © [PromptMatrix](https://github.com/jachinsaikiasonowal/promptmatrix)
