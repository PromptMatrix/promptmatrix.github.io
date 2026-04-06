# PromptMatrix - Open Source Agent Directives

## Mission
Ensure this repository remains a pure, extremely performant, local-first open-source application. Your core directive is to maintain seamless self-hosting capability for developers.

## Architectural Constraints (CRITICAL)
- **Zero Third-Party Cloud Dependencies:** Do not inject any external managed services, remote caches, or commercial billing APIs into this codebase.
- **Local-First Executability:** The system must run flawlessly out-of-the-box using purely local SQLite databases. No external accounts should be required for a developer to clone and boot the application locally.
- **Framework Stack:** Strict compliance with native FastAPI for the backend.

## Security & Workflow
- Do not introduce `.env` defaults that look like or simulate production keys.
- Ensure the `README` always accurately reflects the self-hosted nature of the tool.
- All frontend routing and UI configurations must be namespace-safe for static deployments like GitHub Pages.
