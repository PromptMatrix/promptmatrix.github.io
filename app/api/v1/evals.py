import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import PromptVersion, Prompt, Environment, Project, EvalKey, AuditLog
from app.core.auth import get_current_user_and_org, encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/api/v1/evals", tags=["evals"])

# BUG-01 FIX: Complete provider config — Groq and Mistral now fully supported
PROVIDER_CONFIG = {
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "get_headers": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        "get_body": lambda model, prompt: {"model": model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]},
        "parse_text": lambda r: r["content"][0]["text"],
        "parse_tokens": lambda r: (r["usage"]["input_tokens"], r["usage"]["output_tokens"]),
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "get_headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "get_body": lambda model, prompt: {"model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "max_tokens": 1024},
        "parse_text": lambda r: r["choices"][0]["message"]["content"],
        "parse_tokens": lambda r: (r["usage"]["prompt_tokens"], r["usage"]["completion_tokens"]),
    },
    "google": {
        "url": None,  # built dynamically with model + key
        "get_url": lambda model, key: f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        "get_headers": lambda key: {"Content-Type": "application/json"},
        "get_body": lambda model, prompt: {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 1024}},
        "parse_text": lambda r: r["candidates"][0]["content"]["parts"][0]["text"],
        "parse_tokens": lambda r: (r.get("usageMetadata", {}).get("promptTokenCount", 0), r.get("usageMetadata", {}).get("candidatesTokenCount", 0)),
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "get_headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "get_body": lambda model, prompt: {"model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "max_tokens": 1024},
        "parse_text": lambda r: r["choices"][0]["message"]["content"],
        "parse_tokens": lambda r: (r["usage"]["prompt_tokens"], r["usage"]["completion_tokens"]),
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "get_headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "get_body": lambda model, prompt: {"model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "max_tokens": 1024},
        "parse_text": lambda r: r["choices"][0]["message"]["content"],
        "parse_tokens": lambda r: (r["usage"]["prompt_tokens"], r["usage"]["completion_tokens"]),
    },
}

VALID_PROVIDERS = list(PROVIDER_CONFIG.keys())


class RunEvalIn(BaseModel):
    version_id: str
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5"
    api_key: str = ""
    test_input: str = ""
    eval_type: str = "llm_judge"  # rule_based | llm_judge | both

class SaveKeyIn(BaseModel):
    provider: str
    api_key: str
    label: str = ""


def _rule_based_eval(content: str) -> dict:
    """Zero-dependency, instant eval across 6 dimensions."""
    score_map = {}
    words = len(content.split())

    # Role clarity: starts with "You are" or defines persona
    role_score = 9.0 if re.search(r'^\s*you are', content.lower()) else (
        6.0 if re.search(r'^\s*(act as|your role|as an)', content.lower()) else 3.0
    )
    score_map["role_clarity"] = role_score

    # Instruction quality: imperative verbs, clear commands
    imperatives = ["always", "never", "respond", "provide", "avoid", "ensure", "do not", "must", "only", "focus"]
    matches = sum(1 for kw in imperatives if kw in content.lower())
    score_map["instruction_quality"] = min(10.0, 3.0 + matches * 1.0)

    # Output format: specifies expected output
    format_kws = ["json", "markdown", "bullet", "numbered", "list", "format:", "output:", "respond with", "structure"]
    fmt_score = min(10.0, 4.0 + sum(1.5 for kw in format_kws if kw in content.lower()))
    score_map["output_format"] = fmt_score

    # Variable usage: {{variables}} detected
    vars_found = len(re.findall(r'\{\{[\w_]+\}\}', content))
    score_map["variable_usage"] = min(10.0, 5.0 + vars_found * 1.5) if vars_found > 0 else 6.0

    # Length appropriateness: 50–800 words is optimal
    if words < 20:
        score_map["length"] = 2.0
    elif words < 50:
        score_map["length"] = 5.0
    elif words <= 800:
        score_map["length"] = 9.0
    else:
        score_map["length"] = max(5.0, 9.0 - (words - 800) / 200)

    # Safety: no PII or secret patterns
    secret_patterns = [r'sk-[a-zA-Z0-9]{20,}', r'\b\d{3}-\d{2}-\d{4}\b', r'\b\d{16}\b', r'\bpassword\s*[:=]', r'xox[baprs]-']
    pii_found = any(re.search(p, content) for p in secret_patterns)
    score_map["safety"] = 2.0 if pii_found else 9.0

    overall = round(sum(score_map.values()) / len(score_map), 1)
    passed = overall >= 7.0
    return {
        "overall_score": overall,
        "passed": passed,
        "threshold": 7.0,
        "criteria": score_map,
        "strengths": [k for k, v in score_map.items() if v >= 8],
        "issues": [k for k, v in score_map.items() if v < 5],
        "suggestions": _rule_based_suggestions(score_map),
        "eval_type": "rule_based",
        "provider": "",
        "model": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "duration_ms": 0,
    }


def _rule_based_suggestions(score_map: dict) -> list:
    suggestions = []
    if score_map.get("role_clarity", 10) < 6:
        suggestions.append("Start with 'You are a [role]...' to define the assistant's persona clearly.")
    if score_map.get("instruction_quality", 10) < 6:
        suggestions.append("Add imperative instructions: 'Always...', 'Never...', 'Respond with...'")
    if score_map.get("output_format", 10) < 6:
        suggestions.append("Specify the expected output format (JSON, markdown, bullet list, etc.)")
    if score_map.get("variable_usage", 10) < 6:
        suggestions.append("Use {{variable_name}} syntax for dynamic values instead of hardcoding them.")
    if score_map.get("length", 10) < 5:
        suggestions.append("The prompt is too short — add more specific instructions and context.")
    if score_map.get("safety", 10) < 5:
        suggestions.append("Remove any hardcoded secrets, API keys, or PII from the prompt content.")
    return suggestions

async def _llm_eval(content: str, test_input: str, provider: str, model: str, api_key: str) -> dict:
    """LLM-as-judge eval using BYOK. Key is deleted from scope immediately after use."""
    import time
    import json
    import httpx

    if provider not in PROVIDER_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'. Valid: {', '.join(VALID_PROVIDERS)}")

    judge_prompt = f"""You are a senior prompt engineer evaluating a system prompt for quality.

Evaluate across these dimensions (score 1-10 each):
- clarity: How unambiguous are the instructions? (1=contradictory, 10=crystal clear)
- specificity: How precise and constrained? (1=too vague, 10=highly specific with examples)
- safety: Resistant to misuse? (1=dangerous, 10=robust guardrails)
- completeness: Covers full expected behavior? (1=missing critical parts, 10=comprehensive)
- instruction_quality: Are instructions actionable? (1=passive/vague, 10=imperative/ordered)
- output_format: Is output format specified? (1=none, 10=explicit format with examples)

Prompt to evaluate:
---
{content}
---
Test input (if any): {test_input or "(none)"}

Respond ONLY with valid JSON:
{{"clarity": 0, "specificity": 0, "safety": 0, "completeness": 0, "instruction_quality": 0, "output_format": 0, "strengths": [], "issues": [], "suggestions": []}}"""

    cfg = PROVIDER_CONFIG[provider]
    t = time.monotonic()
    key = api_key  # local ref — deleted in finally block
    try:
        url = cfg.get("get_url", lambda m, k: cfg["url"])(model, key)
        headers = cfg["get_headers"](key)
        body = cfg["get_body"](model, judge_prompt)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
        raw = resp.json()
        text = cfg["parse_text"](raw)
        tokens_in, tokens_out = cfg["parse_tokens"](raw)
        clean = text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        criteria = {k: float(v) for k, v in data.items() if k not in ("strengths", "issues", "suggestions") and isinstance(v, (int, float))}
        overall = round(sum(criteria.values()) / len(criteria), 1) if criteria else 5.0
        return {
            "overall_score": overall,
            "passed": overall >= 7.0,
            "threshold": 7.0,
            "criteria": criteria,
            "strengths": data.get("strengths", []),
            "issues": data.get("issues", []),
            "suggestions": data.get("suggestions", []),
            "eval_type": "llm_judge",
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "duration_ms": round((time.monotonic() - t) * 1000),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM eval failed ({provider}): {str(e)}")
    finally:
        del key  # BYOK: explicit scope delete

@router.post("/run")
async def run_eval(
    body: RunEvalIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    v = db.query(PromptVersion).filter(PromptVersion.id == body.version_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    prompt = db.query(Prompt).filter(Prompt.id == v.prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    env = db.query(Environment).filter(Environment.id == prompt.environment_id).first()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    project = db.query(Project).filter(Project.id == env.project_id).first()
    if not project or project.org_id != member.org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    if body.eval_type == "rule_based" or body.provider == "rule_based":
        result = _rule_based_eval(v.content)
    else:
        if body.provider not in VALID_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown provider '{body.provider}'. Valid: {', '.join(VALID_PROVIDERS)}")
        if not body.api_key or body.api_key in ("", "none"):
            k = db.query(EvalKey).filter(
                EvalKey.org_id == member.org_id,
                EvalKey.provider == body.provider
            ).first()
            if not k:
                raise HTTPException(status_code=400, detail=f"No saved key for '{body.provider}'. Pass api_key in request or save one via /api/v1/evals/keys")
            api_key_to_use = decrypt_api_key(k.encrypted_key)
        else:
            api_key_to_use = body.api_key
        result = await _llm_eval(v.content, body.test_input, body.provider, body.model, api_key_to_use)

    v.last_eval_score = result["overall_score"]
    v.last_eval_passed = result["passed"]
    v.last_eval_at = datetime.now(timezone.utc)
    db.add(AuditLog(
        org_id=member.org_id, actor_id=user.id, actor_email=user.email,
        action="eval.run", resource_type="version", resource_id=v.id,
        extra={"score": result["overall_score"], "passed": result["passed"],
               "eval_type": result["eval_type"], "provider": result.get("provider", "")}
    ))
    db.commit()
    return result


@router.get("/providers")
async def list_providers():
    """Returns list of supported LLM providers for eval."""
    return {"providers": VALID_PROVIDERS}

@router.get("/keys")
async def list_eval_keys(
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    keys = db.query(EvalKey).filter(EvalKey.org_id == member.org_id).all()
    return {"keys": [{
        "id": k.id,
        "provider": k.provider,
        "hint": k.key_hint,
        "label": k.label,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    } for k in keys]}

@router.post("/keys")
async def save_eval_key(
    body: SaveKeyIn,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    encrypted = encrypt_api_key(body.api_key)
    hint = body.api_key[-4:] if len(body.api_key) >= 4 else "****"
    k = EvalKey(
        org_id=member.org_id,
        provider=body.provider,
        encrypted_key=encrypted,
        key_hint=hint,
        label=body.label,
        created_by_id=user.id,
    )
    db.add(k)
    db.commit()
    return {"message": "Saved", "id": k.id}

@router.delete("/keys/{key_id}")
async def delete_eval_key(
    key_id: str,
    auth=Depends(get_current_user_and_org),
    db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org")
    k = db.query(EvalKey).filter(
        EvalKey.id == key_id,
        EvalKey.org_id == member.org_id
    ).first()
    if not k:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(k)
    db.commit()
    return {"message": "Removed"}
