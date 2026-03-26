---
name: promptmatrix-oss
description: Core architectural knowledge for PromptMatrix (Public/Local-First Edition). Load this for any task involving the sanitized codebase.
---

# PromptMatrix — Local-First Architecture

## Core Mission
PromptMatrix is a **prompt governance backend** for AI applications. It transitions prompt management from hardcoded variables to a version-controlled, auditable, and instantly updatable registry.

## Local-First Constraint
The public version of PromptMatrix is built for **single-user, local-host environments**. 
- **Single Admin**: Only the first user to register can access the system. Subsequent registrations are blocked by the backend.
- **Local Workspace**: On first registration, the system automatically seeds a "Local Workspace" and "Default Project".
- **Zero SaaS dependency**: Removed payment webhooks, team invitations, and cloud-forced database requirements.

---

## Technical Stack (Sanitized)
```
Runtime:     FastAPI (Python 3.10+)
Database:    SQLAlchemy (Default: SQLite for local persistence)
Auth:        JWT (Access + Refresh tokens) + API Key hashing
Governance:  Engineer-controlled approval gate for all prompt changes
Frontend:    Vanilla JS + CSS (Single-page dashboard)
```

## Critical Serve Path: `GET /pm/serve/{key}`
This is the **hot path**. When an application needs a prompt, it calls this URL.
1. Authenticates via Bearer token (API Key).
2. Looks up the approved `live_version` for the given key.
3. Substitutes `{{variables}}` from the `?vars=` query parameter.
4. Returns the safe, approved content.

## State Machine: Prompt Lifecycle
```
draft → pending_review → approved → archived
                      ↘ rejected
```
- **Draft**: The proposer is editing.
- **Pending Review**: Submitted to the "Approvals" queue.
- **Approved**: Currently served in the application.
- **Rejected**: Engineer denied the change (requires reason).

---

## Development Constraints
1. **FAIL-SAFE**: If LLM eval or external calls fail, the system should allow deployment (optional but recommended default).
2. **AUDIT-READY**: Every state change (create, submit, approve, reject) must write to the `AuditLog`.
3. **ZERO-REDEPLOY**: Changes go live in 10 seconds without restarting the host application.

---

## File Map
- `main.py`: App entry point.
- `app/api/v1/auth.py`: Sanitized for single-user registration.
- `app/api/v1/prompts.py`: Core CRUD and versioning logic.
- `app/api/v1/approvals.py`: Approval queue management.
- `app/models.py`: Database schema (Organisation, User, Project, Environment, Prompt, Version).
- `app/config.py`: Local settings (defaulting to SQLite).
- `index.html`: Marketing/landing page (Updated to v15-sanitized for OSS).
- `dashboard.html`: The admin interface.
