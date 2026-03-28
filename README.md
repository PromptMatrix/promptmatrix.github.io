<div align="center">
  <img src="https://via.placeholder.com/800x200/000400/00E676?text=PromptMatrix" alt="PromptMatrix Banner" />
  
  <h3>The Governance Engine for AI Systems</h3>
  
  <p>
    <b>Stop hardcoding your LLM prompts. Start governing them.</b>
  </p>

  <p>
    <a href="https://promptmatrix.github.io">Website</a> •
    <a href="https://app.promptmatrix.io">Managed Cloud</a> •
    <a href="#-quick-start">Quick Start</a>
  </p>
</div>

---

**PromptMatrix** is high-performance, open-source infrastructure for AI engineering teams. It centralizes your agent prompts into a version-controlled, auditable, and evaluated registry, enabling instant updates via sub-10ms APIs without ever redeploying your codebase.

👉 **Looking for multi-player scaling?** While this repository provides the complete local-first engine, production teams using approval workflows and role-based access use [PromptMatrix Cloud](https://app.promptmatrix.io).

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

## ✨ Enterprise-Grade Features (Local Open Source Version)

*   **⏱️ Zero-Downtime Hot Swaps:** Update your LLM instructions in real time. Changes propagate in milliseconds.
*   **⏪ Immutable Version History:** 1-click rollbacks for broken prompts. Never lose a historical state.
*   **⚖️ Built-in LLM-As-Judge Evals:** Natively test your prompts against Anthropic, OpenAI, or Google before deploying them to production.
*   **🛡️ Cryptographic Operations:** Integration API keys are securely AES-256-GCM encrypted in the database.
*   **🔌 Universal API:** Low-latency `GET` endpoints with fail-open caching for ultimate reliability.

---

## 🚀 One-Click Quick Start

PromptMatrix is fiercely independent. It runs purely on standard SQLite with zero external database dependencies for local setups.

### Windows
Double-click **`start.bat`** to handle virtual environments, dependencies, and database seeding automatically.

### Linux / macOS
```bash
chmod +x start.sh
./start.sh
```

**Access the Visual Governance Dashboard at:** `http://localhost:8000/dashboard`

---

## 🛠 Manual Installation

If you prefer explicit control:

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

## ☁️ PromptMatrix Local vs. Cloud

| Feature | Local Open Source | [PromptMatrix Cloud](https://app.promptmatrix.io) |
| :--- | :--- | :--- |
| **Seat Limit** | 1 (Single Admin) | Unlimited Teams |
| **Database** | SQLite (Local) | Globally distributed PostgreSQL |
| **Evals** | Included | Included |
| **Role-Based Approvals** | ❌ | ✅ (Engineers review Editors) |
| **SLAs & Enterprise SSO** | ❌ | ✅ |

*Ready to scale? [Upgrade to the Managed Cloud](https://app.promptmatrix.io) today.*

---

## 📄 License
MIT © [PromptMatrix](https://github.com/PromptMatrix)
