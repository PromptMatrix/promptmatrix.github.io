import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models import PromptVersion, Prompt, Environment, Project, EvalKey, AuditLog
from app.core.auth import get_current_user_and_org, require_role, encrypt_api_key, decrypt_api_key

router = APIRouter(prefix="/api/v1/evals", tags=["evals"])

class RunEvalIn(BaseModel):
    version_id: str
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    test_input: str = ""
    eval_type: str = "llm_judge"

class SaveKeyIn(BaseModel):
    provider: str
    api_key: str
    label: str = ""

def _rule_based_eval(content: str) -> dict:
    score_map = {}
    words = len(content.split())
    score_map["length"] = min(10.0, max(1.0, words / 20))
    vars_found = len(re.findall(r'\{\{[\w_]+\}\}', content))
    score_map["variable_usage"] = min(10.0, 5.0 + vars_found * 1.5)
    imperatives = ["you are", "always", "never", "respond", "provide", "avoid", "ensure"]
    matches = sum(1 for kw in imperatives if kw in content.lower())
    score_map["clarity"] = min(10.0, 4.0 + matches * 1.2)
    pii_patterns = [r'\b\d{3}-\d{2}-\d{4}\b', r'\b\d{16}\b', r'\bpassword\s*[:=]']
    pii_found = any(re.search(p, content) for p in pii_patterns)
    score_map["safety"] = 2.0 if pii_found else 9.0
    overall = round(sum(score_map.values()) / len(score_map), 1)
    passed = overall >= 7.0
    return {
        "overall_score": overall,
        "passed": passed,
        "threshold": 7.0,
        "criteria": score_map,
        "strengths": [k for k, v in score_map.items() if v >= 8],
        "issues": [k for k, v in score_map.items() if v < 6],
        "eval_type": "rule_based",
        "duration_ms": 0,
    }

async def _llm_eval(content: str, test_input: str, provider: str, model: str, api_key: str) -> dict:
    import time
    import httpx
    judge_prompt = f"""Evaluate system prompt.
Prompt:
{content}
Input: {test_input or "(none)"}
Respond JSON: {{"clarity": 0-10, "specificity": 0-10, "safety": 0-10, "completeness": 0-10, "tone_consistency": 0-10, "strengths": [], "issues": []}}"""
    t = time.monotonic()
    headers = {"Content-Type": "application/json"}
    payload_map = {
        "anthropic": {
            "url": "https://api.anthropic.com/v1/messages",
            "headers": {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            "body": {"model": model, "max_tokens": 512, "messages": [{"role": "user", "content": judge_prompt}]},
            "parse": lambda r: r["content"][0]["text"]
        },
        "openai": {
            "url": "https://api.openai.com/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {api_key}"},
            "body": {"model": model, "messages": [{"role": "user", "content": judge_prompt}], "max_tokens": 512},
            "parse": lambda r: r["choices"][0]["message"]["content"]
        },
        "google": {
            "url": f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            "headers": {},
            "body": {"contents": [{"parts": [{"text": judge_prompt}]}]},
            "parse": lambda r: r["candidates"][0]["content"]["parts"][0]["text"]
        },
    }
    cfg = payload_map.get(provider)
    if not cfg:
        raise HTTPException(status_code=400, detail="Provider unknown")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(cfg["url"], headers={**headers, **cfg["headers"]}, json=cfg["body"])
            resp.raise_for_status()
            text = cfg["parse"](resp.json())
        import json
        clean = text.strip().replace("```json", "").replace("```", "")
        data = json.loads(clean)
        criteria = {k: float(v) for k, v in data.items() if k not in ("strengths", "issues") and isinstance(v, (int, float))}
        overall = round(sum(criteria.values()) / len(criteria), 1) if criteria else 5.0
        return {
            "overall_score": overall,
            "passed": overall >= 7.0,
            "threshold": 7.0,
            "criteria": criteria,
            "strengths": data.get("strengths", []),
            "issues": data.get("issues", []),
            "eval_type": "llm_judge",
            "provider": provider,
            "model": model,
            "duration_ms": round((time.monotonic() - t) * 1000),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

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
        if not body.api_key or body.api_key == "none":
            k = db.query(EvalKey).filter(
                EvalKey.org_id == member.org_id, 
                EvalKey.provider == body.provider
            ).first()
            if not k:
                raise HTTPException(status_code=400, detail=f"No saved evaluation API key found for provider '{body.provider}'")
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
        extra={"score": result["overall_score"], "passed": result["passed"], "provider": body.provider}
    ))
    db.commit()
    return result

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
