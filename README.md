# PromptMatrix — Every Prompt. One Governed Registry.

PromptMatrix is a prompt governance infrastructure for AI teams. It pulls every hardcoded prompt in your codebase into a single registry — versioned, auditable, and instantly updatable via a serve endpoint.

## Features

- **Central Registry:** One source of truth for all prompts.
- **Version Control:** Full history and 1-click rollback.
- **Approval Workflow:** Engineers review and approve changes from PMs or Marketers.
- **Live Serve Endpoint:** Agents call `GET /pm/serve/{key}` to get the latest approved prompt.
- **Local-First / Self-Host:** Runs on SQLite with Zero-Setup.
- **Free & Open Source:** MIT Licensed.

## Quick Start (Self-Host with SQLite)

```bash
# 1. Clone the repository
git clone https://github.com/PromptMatrix/promptmatrix.git
cd promptmatrix

# 2. Install dependencies
pip install -r requirements.txt

# 3. Setup environment
cp .env.example .env
# Edit .env and set:
# DATABASE_URL=sqlite:///./promptmatrix.db
# JWT_SECRET_KEY=yoursecret
# ENCRYPTION_KEY=yourkey

# 4. Run migrations
alembic upgrade head

# 5. Start the server
uvicorn main:app --reload --port 8000
```

- **Landing Page:** [http://localhost:8000/](http://localhost:8000/)
- **Dashboard:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
- **API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

## Deployment (Vercel + Supabase)

See [DEPLOY.md](DEPLOY.md) for instructions on deploying to Vercel for a production-ready cloud version.

## License

MIT License. See [LICENSE](LICENSE) for details.
