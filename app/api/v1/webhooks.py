"""
Webhooks — /api/v1/webhooks/
=============================
Inbound: Razorpay payment events → update org plan to 'founding'

Note: Outbound webhooks (notifying customers when versions are approved etc.)
are on the roadmap. The Webhook model exists but delivery is not yet implemented.
Do not surface outbound webhooks in the UI until the delivery worker is built.
"""

import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Organisation, AuditLog
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _verify_razorpay_signature(payload: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 verification. Uses compare_digest to prevent timing attacks."""
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
):
    """
    Razorpay sends this on payment.captured events.
    We update the org plan to 'founding' and log the event.

    The payment link must include a note/description containing the org_id
    so we know which org to upgrade.
    """
    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    body = await request.body()

    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing signature header")

    if not _verify_razorpay_signature(body, x_razorpay_signature, settings.razorpay_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("event")

    if event_type == "payment.captured":
        payment = event.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        org_id = notes.get("org_id")
        amount = payment.get("amount", 0)  # in paise
        payment_id = payment.get("id", "")

        if org_id:
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                org = db.query(Organisation).filter(Organisation.id == org_id).first()
                if org and org.plan == "free":
                    org.plan = "founding"
                    db.add(AuditLog(
                        org_id=org_id,
                        actor_id=None,
                        actor_email="razorpay-webhook",
                        action="org.plan_upgraded",
                        resource_type="org",
                        resource_id=org_id,
                        extra={
                            "from": "free",
                            "to": "founding",
                            "payment_id": payment_id,
                            "amount_inr": amount / 100,
                        }
                    ))
                    db.commit()
            finally:
                db.close()

    # Always return 200 — Razorpay retries on non-200
    return {"status": "ok"}
