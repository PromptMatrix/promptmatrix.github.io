import logging
from app.config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)

def _html_wrapper(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{font-family: 'Courier New', monospace; background:#080808; color:#F2EFE8; margin:0; padding:32px;}}
  .container {{max-width:520px; margin:0 auto;}}
  .logo {{font-size:20px; letter-spacing:4px; color:#F2EFE8; margin-bottom:32px;}}
  .logo em {{color:#00e676; font-style:normal;}}
  h1 {{font-size:18px; letter-spacing:2px; color:#F2EFE8; margin-bottom:16px; text-transform:uppercase;}}
  p {{font-size:14px; line-height:1.8; color:#888070; margin-bottom:16px;}}
  .btn {{display:inline-block; background:#00e676; color:#080808; padding:12px 28px;
          font-family:inherit; font-size:12px; letter-spacing:2px; text-transform:uppercase;
          text-decoration:none; margin:16px 0;}}
  .code {{background:#0F0F0F; border:1px solid #1E1E1E; padding:12px 16px;
          font-size:13px; color:#00e676; letter-spacing:1px; margin:16px 0;}}
  .footer {{margin-top:40px; padding-top:20px; border-top:1px solid #1E1E1E;
              font-size:11px; color:#888070; letter-spacing:1px;}}
</style>
</head><body>
<div class="container">
  <div class="logo">PROMPT<em>MATRIX</em></div>
  <h1>{title}</h1>
  {body}
  <div class="footer">
    PromptMatrix · Open Source Prompt Governance ·
    <a href="https://github.com/jachinsaikiasonowal/promptmatrix" style="color:#00e676;">GitHub</a>
  </div>
</div></body></html>"""

async def send_email(to: str, subject: str, html: str) -> bool:
    if not settings.resend_api_key:
        log.info(f"[EMAIL SKIP] To: {to} | Subject: {subject}")
        return False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                }
            )
            if r.status_code >= 400:
                log.warning(f"[EMAIL FAILED] {r.status_code} | To: {to}")
                return False
            return True
    except Exception as e:
        log.warning(f"[EMAIL ERROR] {e} | To: {to}")
        return False
    return False

async def send_welcome(email: str, org_name: str, plan: str):
    body = f"""
    <p>Your PromptMatrix workspace is live.</p>
    <div class="code">Organisation: {org_name}<br>Plan: {plan.upper()}</div>
    <p>Three things to do first:</p>
    <p>1. Create your first prompt key in the Registry<br>
       2. Copy the serve endpoint URL — your apps call this<br>
       3. Connect your API keys</p>
    <a href="{settings.frontend_url}" class="btn">Open Dashboard →</a>
    """
    await send_email(email, "PromptMatrix · Your workspace is ready",
                     _html_wrapper("WORKSPACE READY", body))

async def send_approval_needed(
    approver_email: str, requester_name: str,
    prompt_key: str, version_num: int, env_name: str,
    note: str, dashboard_url: str
):
    body = f"""
    <p>{requester_name} submitted a prompt change for your review.</p>
    <div class="code">
    Prompt: {prompt_key}<br>
    Version: v{version_num}<br>
    Environment: {env_name.upper()}<br>
    Note: {note or "—"}
    </div>
    <p>Review the diff, check the eval score, then approve or reject.</p>
    <a href="{dashboard_url}/approvals" class="btn">Review Now →</a>
    """
    await send_email(
        approver_email,
        f"PromptMatrix · Review needed: {prompt_key} v{version_num}",
        _html_wrapper("APPROVAL NEEDED", body)
    )

async def send_version_approved(
    requester_email: str, approver_name: str,
    prompt_key: str, version_num: int, env_name: str
):
    body = f"""
    <p>Your prompt change was approved and is now live.</p>
    <div class="code">
    Prompt: {prompt_key}<br>
    Version: v{version_num} · LIVE<br>
    Environment: {env_name.upper()}<br>
    Approved by: {approver_name}
    </div>
    <p>Agents calling <code>/pm/serve/{prompt_key}</code> now receive v{version_num}.</p>
    """
    await send_email(
        requester_email,
        f"PromptMatrix · Approved: {prompt_key} v{version_num} is live",
        _html_wrapper("VERSION APPROVED", body)
    )

async def send_version_rejected(
    requester_email: str, reviewer_name: str,
    prompt_key: str, version_num: int, reason: str, dashboard_url: str
):
    body = f"""
    <p>Your prompt change was not approved.</p>
    <div class="code">
    Prompt: {prompt_key}<br>
    Version: v{version_num}<br>
    Rejected by: {reviewer_name}<br>
    Reason: {reason}
    </div>
    <p>Address the feedback, create a new version, and resubmit.</p>
    <a href="{dashboard_url}/registry" class="btn">Edit Prompt →</a>
    """
    await send_email(
        requester_email,
        f"PromptMatrix · Rejected: {prompt_key} v{version_num}",
        _html_wrapper("VERSION REJECTED", body)
    )

async def send_eval_failed(
    user_email: str, prompt_key: str, version_num: int,
    score: float, threshold: float, issues: list
):
    issues_html = "".join(f"<br>· {i}" for i in issues)
    body = f"""
    <p>Eval did not pass the threshold for this environment.</p>
    <div class="code">
    Prompt: {prompt_key} · v{version_num}<br>
    Score: {score:.1f} / 10<br>
    Threshold: {threshold:.1f}<br>
    Gap: {threshold - score:.1f} points needed{issues_html}
    </div>
    <p>Fix the issues above, re-run the eval, then resubmit for approval.</p>
    """
    await send_email(
        user_email,
        f"PromptMatrix · Eval failed: {prompt_key} v{version_num} ({score:.1f}/{threshold:.1f})",
        _html_wrapper("EVAL FAILED", body)
    )

async def send_invite(
    invitee_email: str, inviter_name: str, org_name: str,
    role: str, temp_password: str
):
    body = f"""
    <p>{inviter_name} invited you to {org_name} on PromptMatrix.</p>
    <div class="code">
    Email: {invitee_email}<br>
    Role: {role.upper()}<br>
    Temp password: {temp_password}
    </div>
    <p>Log in and change your password immediately in Settings.</p>
    <a href="{settings.frontend_url}" class="btn">Accept Invite →</a>
    """
    await send_email(
        invitee_email,
        f"PromptMatrix · You're invited to {org_name}",
        _html_wrapper("YOU'RE INVITED", body)
    )
