import re
from typing import List, Tuple

# Simple yet effective patterns to detect common secrets
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{32,}", "OpenAI Key"),
    (r"xox[bapors]-[a-zA-Z0-9-]{10,}", "Slack Token"),
    (r'(?i)password\s*[:=]\s*["\'][^"\']+["\']', "Plaintext Password"),
    (r"(?i)bearer\s+[a-zA-Z0-9-._~+/]{20,}", "Bearer Token"),
]


def analyze_prompt_safety(content: str) -> List[Tuple[str, str]]:
    """Detects potential security risks in prompt content."""
    risks = []
    for pattern, name in SECRET_PATTERNS:
        if re.search(pattern, content):
            risks.append((name, pattern))
    return risks


def redact_identified_secrets(content: str) -> str:
    """Automatically redacts identified secrets before they hit the database."""
    redacted = content
    for pattern, name in SECRET_PATTERNS:
        redacted = re.sub(
            pattern, f"[REDACTED_{name.upper().replace(' ', '_')}]", redacted
        )
    return redacted
