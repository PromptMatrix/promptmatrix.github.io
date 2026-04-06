import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import AuditLog


class AuditService:
    @staticmethod
    def log_action(
        db: Session,
        org_id: str,
        actor_id: Optional[str],
        actor_email: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        extra: Optional[dict] = None,
    ) -> AuditLog:
        """
        Creates a cryptographically chain-linked audit log entry.
        Each entry contains a hash of its own data + the hash of the previous entry.
        """
        ts = datetime.now(timezone.utc).replace(microsecond=0)
        
        # 1. Get the previous hash for this organisation
        prev_log = (
            db.query(AuditLog)
            .filter(AuditLog.org_id == org_id)
            .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
            .first()
        )
        prev_hash = prev_log.integrity_hash if prev_log else "GENESIS_BLOCK"

        # 2. Generate the new integrity hash (Chain Link)
        # Format: action:resource_id:timestamp:previous_hash
        data_str = f"{action}:{resource_id or ''}:{ts.isoformat()}:{prev_hash}"
        new_hash = hashlib.sha256(data_str.encode()).hexdigest()

        # 3. Create the log entry
        log = AuditLog(
            org_id=org_id,
            actor_id=actor_id,
            actor_email=actor_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            extra=extra or {},
            created_at=ts,
            integrity_hash=new_hash,
        )
        
        db.add(log)
        return log

    @staticmethod
    def verify_chain(db: Session, org_id: str) -> bool:
        """
        Verifies the integrity of the audit chain for a given organisation.
        """
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.org_id == org_id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .all()
        )
        
        current_prev_hash = "GENESIS_BLOCK"
        for log in logs:
            # Ensure timestamp is normalized (some DBs might add/strip micro/tz)
            ts_str = log.created_at.replace(microsecond=0)
            if ts_str.tzinfo is None:
                ts_str = ts_str.replace(tzinfo=timezone.utc)
            
            data_str = f"{log.action}:{log.resource_id or ''}:{ts_str.isoformat()}:{current_prev_hash}"
            expected_hash = hashlib.sha256(data_str.encode()).hexdigest()
            
            if log.integrity_hash != expected_hash:
                return False
            
            current_prev_hash = log.integrity_hash
            
        return True
