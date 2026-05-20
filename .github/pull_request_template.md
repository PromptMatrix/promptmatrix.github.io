## Summary
<!-- One sentence: what this PR does and why. -->

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that changes existing behavior)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Security fix

## What Changed
<!-- Bullet-point list of meaningful changes. Be specific. -->
-
-

## Testing
<!-- Describe how you tested this. -->
- [ ] All existing tests pass (`pytest -v`)
- [ ] New tests added for changed behavior
- [ ] Tested manually in local environment (`APP_ENV=development`)

## Local-First Constraint
<!-- PromptMatrix is local-first. No mandatory cloud dependencies in the OSS version. -->
- [ ] This PR does NOT introduce mandatory external services (Redis, S3, Stripe, etc.)
- [ ] This PR does NOT add cloud-only credentials to `.env.example`
- [ ] All new functionality works with SQLite out of the box

## Security Checklist
- [ ] No secrets, API keys, or PII committed
- [ ] Input validated and sanitized
- [ ] New endpoints are role-gated where appropriate
- [ ] No raw API keys logged or stored

## Related Issues
<!-- Closes #123 -->
