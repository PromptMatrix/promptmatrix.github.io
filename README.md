# ⚡️ PromptMatrix — The One-Stop Registry for AI Prompts

> **Stop hardcoding. Start Governing.** 

PromptMatrix is a high-performance, open-source infrastructure designed for AI engineering teams. It centralizes your prompts into a single, versioned registry, enabling instant updates via API without redeploying your code.

---

## 🎨 Why PromptMatrix?

*   **⚡️ Zero-Downtime Updates:** Update system prompts in real-time. No code changes, no redeploys.
*   **📂 Structured Registry:** Organize prompts by project, environment (Production, Staging, Draft), and version.
*   **⚖️ Governance & Audit:** Full version history with 1-click rollbacks for broken prompts.
*   **🔌 Universal API:** Low-latency `GET` endpoint for any AI agent or service.
*   **📦 Self-Host Ready:** Runs on SQLite/PostgreSQL with a single command.

---

## 🚀 One-Click Quick Start

### For Windows:
Double-click **`start.bat`** — it will handle everything (venv, dependencies, database setup).

### For Linux / macOS:
```bash
chmod +x start.sh
./start.sh
```

---

## 🛠 Manual Setup

If you prefer to set it up manually:

```bash
# 1. Clone & Enter
git clone https://github.com/PromptMatrix/PromptMatrix.git
cd PromptMatrix

# 2. Virtual Env & Deps
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Environment
cp .env.example .env
# Important: Open .env and set your secrets!

# 4. Initialize Database
alembic upgrade head

# 5. Launch
python -m uvicorn main:app --reload --port 8000
```

---

## 🖥 Access Points

*   **🏠 App Dashboard:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
*   **📜 API Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
*   **📋 Static Dashboard:** Open `standalone.html` in any browser (Local-only preview).

---

## 🌐 Deployment (Cloud)

For production-grade deployments (Vercel + Supabase), refer to our [Deployment Guide (DEPLOY.md)](DEPLOY.md).

---

## 📄 License

MIT © [PromptMatrix](https://github.com/PromptMatrix)
