# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ |
| Older releases | ❌ |

We support only the latest release. Update before reporting.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Send details to: **security@promptmatrix.io**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Your suggested fix (optional)

We respond within **48 hours** and will credit you in the release notes after a patch ships (unless you prefer anonymity).

---

## Disclosure Policy

1. You report privately → we confirm receipt within 48 hours.
2. We investigate and develop a fix.
3. We release the patch and notify you.
4. We publicly disclose after users have had reasonable time to update (typically 7–14 days after patch release).

---

## Scope

**In scope:**
- Authentication bypass / JWT vulnerabilities
- SQL injection
- Privilege escalation (role bypass)
- API key exposure
- SSRF via eval provider calls
- Stored XSS in dashboard

**Out of scope:**
- Issues requiring physical machine access
- Denial of service at the infrastructure level
- Vulnerabilities in dependencies (report upstream)
- Self-inflicted issues from misconfiguring `.env`

---

## Security Architecture Notes

PromptMatrix is a **local-first** tool. The core security properties are:

- **No API keys stored in plaintext.** All API keys are SHA-256 hashed. Eval keys (BYOK) are AES-256-GCM encrypted.
- **BYOK contract.** Keys passed in request bodies are deleted from memory immediately after use and are never logged.
- **Single-user local mode.** In `APP_ENV=development`, registration is locked after the first user. There is no multi-tenant surface.
- **Security headers.** CSP, X-Frame-Options, X-Content-Type-Options, and HSTS (production only) are applied via middleware on every response.
