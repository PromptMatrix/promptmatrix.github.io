<div align="center">

  <img src="https://raw.githubusercontent.com/PromptMatrix/promptmatrix.github.io/main/PromptMatrix.png" alt="PromptMatrix" width="100%">

  <h1>⬡ PromptMatrix</h1>
  <h3>The Governance Engine for AI Systems</h3>

  <p>
    <b>Stop hardcoding your LLM prompts. Start governing them.</b>
  </p>

  <p>
    <a href="https://github.com/PromptMatrix/PromptMatrix/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License" /></a>
    <a href="https://github.com/PromptMatrix/PromptMatrix/releases"><img src="https://img.shields.io/github/v/release/PromptMatrix/PromptMatrix?label=version" alt="Version" /></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" /></a>
    <img src="https://img.shields.io/badge/SQLite-local--first-orange.svg" alt="Local-first SQLite" />
  </p>

  <p>
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-features">Features</a> •
    <a href="#-deployment-models">Deployment Models</a> •
    <a href="#-manual-installation">Manual Installation</a> •
    <a href="https://github.com/PromptMatrix/PromptMatrix/blob/main/LICENSE">MIT License</a>
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
*   **⚖️ Built-in LLM-As-Judge Evals:** Natively test your prompts against Anthropic, OpenAI, or Google before deploying them to production.
*   **🛡️ Cryptographic Security:** Integration API keys are AES-256-GCM encrypted in the database.
*   **🔌 Universal API:** Low-latency `GET` endpoints with fail-open caching for ultimate reliability.
*   **📊 Visual Dashboard:** Full governance UI at `http://localhost:8000/dashboard`.

---

## 🚀 Quick Start

PromptMatrix runs purely on SQLite with zero external database dependencies.

### Windows
Double-click **`start.bat`** — it handles venv creation, dependencies, secret generation, and database migrations automatically.

### Linux / macOS
```bash
chmod +x start.sh
./start.sh
```

**Access the Visual Governance Dashboard at:** `http://localhost:8000/dashboard`

---

## 🛠 Manual Installation

```bash
git clone https://github.com/PromptMatrix/PromptMatrix.git
cd PromptMatrix

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env      # Configure your secrets!
alembic upgrade head

python -m uvicorn main:app --reload --port 8000
```

---

## 📦 Repository Structure

```
PromptMatrix/
├── app/
│   ├── api/v1/          # FastAPI route handlers (auth, prompts, keys, evals, etc.)
│   ├── core/            # Auth logic, policy, email (disabled in local mode)
│   ├── serve/           # Low-latency prompt serving router + cache
│   ├── config.py        # Pydantic settings (reads from .env)
│   ├── database.py      # SQLAlchemy session + SQLite/PostgreSQL engine
│   └── models.py        # ORM models (User, Org, Prompt, etc.)
├── migrations/
│   └── versions/        # Alembic migration files
├── tests/               # pytest test suite (auth, prompts, keys, serve)
├── dashboard.html        # Vue.js governance dashboard (served by FastAPI)
├── index.html            # Landing / entry page
├── main.py               # FastAPI application entry point
├── start.sh              # One-click setup for Linux/macOS
├── start.bat             # One-click setup for Windows
├── .env.example          # Configuration template
├── requirements.txt      # Python dependencies
└── alembic.ini           # Alembic configuration
```

---

## 🚀 Deployment Models

### 🏠 Local / Self-Hosted (This Repository)

- **Single-user, fully autonomous deployment**
- SQLite database (zero external dependencies)
- Perfect for individual developers managing prompts locally
- 100% open source — MIT licensed
- Instant setup: run `./start.sh` or `start.bat`

---

## ⌨️ CLI Utilities (`pmx.py`)

PromptMatrix includes a lightweight CLI for terminal-first prompt engineering. It allows you to push local files directly to the dev environment and pull live prompts back down to your filesystem.

### Setup
Ensure the server is running, then use the Python environment:
```bash
# Windows
venv\Scripts\python.exe pmx.py --help

# Linux / macOS
./venv/bin/python pmx.py --help
```

### Common Commands
*   **Check Status:** `python pmx.py status`
*   **List Prompts:** `python pmx.py list`
*   **Push a Prompt:** `python pmx.py push project.assistant ./prompt.txt`
    *   *Creates/updates the prompt and auto-approves it in development mode.*
*   **Pull a Prompt:** `python pmx.py pull project.assistant ./downloaded.txt`

---

### ☁️ Cloud / Team Version (Coming Soon)

- **Multi-user, team collaboration**
- PostgreSQL backend for production scale
- Role-Based Access Control (RBAC)
- Multi-stage approval workflows
- Managed hosting available

> For team features or production deployments, see the PostgreSQL config in `.env.example` and uncomment `psycopg2-binary` in `requirements.txt`.

---

## 🧪 Running Tests

```bash
# Activate your venv first
source venv/bin/activate  # Windows: venv\Scripts\activate

pytest
```

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines (coming soon).

---

## 📄 License

MIT © [PromptMatrix](https://github.com/PromptMatrix)
