import re
import hashlib
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from app.models import (
    Prompt, PromptVersion, Environment, AuditLog, User, OrgMember
)
from app.core.policy import redact_identified_secrets, analyze_prompt_safety
from app.serve.cache import invalidate_prompt_cache

class PromptService:
    def __init__(self, db: Session):
        self.db = db

    def _generate_integrity_hash(self, action: str, resource_id: str, ts: datetime) -> str:
        """Generate a SHA-256 hash to ensure log integrity."""
        ctx = f"{action}:{resource_id}:{ts.isoformat()}"
        return hashlib.sha256(ctx.encode()).hexdigest()

    async def submit_for_review(self, prompt_id: str, version_id: str, note: str, user: User, member: OrgMember):
        """Submit a version for review and notify engineers."""
        v = self.db.query(PromptVersion).filter(
            PromptVersion.id == version_id, PromptVersion.prompt_id == prompt_id
        ).first()
        if not v:
            raise HTTPException(status_code=404, detail="Version not found")
        
        v.status = "pending_review"
        v.approval_note = note
        
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        self._log_action(
            org_id=member.org_id, user_id=user.id, user_email=user.email,
            action="version.submitted", resource_type="version", resource_id=v.id,
            extra={"prompt_key": prompt.key if prompt else "", "note": note}
        )
        self.db.commit()

        # Notify Engineers
        try:
            from app.core.email import send_approval_needed
            from app.config import get_settings
            settings = get_settings()
            _env = self.db.query(Environment).filter(Environment.id == prompt.environment_id).first() if prompt else None
            _env_name = _env.name if _env else "unknown"
            
            engineers = self.db.query(User).join(OrgMember).filter(
                OrgMember.org_id == member.org_id,
                OrgMember.role.in_(["engineer", "admin", "owner"])
            ).all()
            
            for eng in engineers:
                await send_approval_needed(
                    approver_email=eng.email,
                    requester_name=user.full_name or user.email,
                    prompt_key=prompt.key if prompt else version_id,
                    version_num=v.version_num,
                    env_name=_env_name,
                    note=note,
                    dashboard_url=settings.app_url
                )
        except Exception:
            pass # Don't fail core logic on email error
        
        return v

    async def approve_version(self, prompt_id: str, version_id: str, note: str, user: User, member: OrgMember):
        """Approve a version, make it live, and notify the requester."""
        v = self.db.query(PromptVersion).filter(
            PromptVersion.id == version_id, PromptVersion.prompt_id == prompt_id
        ).first()
        if not v or v.status != "pending_review":
            raise HTTPException(status_code=400, detail="Version not found or not in pending_review")
        
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        
        # Archive old live version
        if prompt.live_version_id and prompt.live_version_id != version_id:
            old = self.db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
            if old:
                old.status = "archived"
        
        v.status = "approved"
        v.approved_by_id = user.id
        v.approved_at = datetime.now(timezone.utc)
        v.approval_note = note
        
        prompt.live_version_id = v.id
        self._apply_optimistic_lock(prompt)
        
        self._log_action(
            org_id=member.org_id, user_id=user.id, user_email=user.email,
            action="version.approved", resource_type="version", resource_id=v.id,
            extra={"prompt_key": prompt.key, "version_num": v.version_num}
        )
        self.db.commit()
        
        await invalidate_prompt_cache(prompt.environment_id, prompt.key)

        # Notify Requester
        try:
            from app.core.email import send_version_approved
            if v.proposed_by_id:
                requester = self.db.query(User).filter(User.id == v.proposed_by_id).first()
                env = self.db.query(Environment).filter(Environment.id == prompt.environment_id).first()
                if requester:
                    await send_version_approved(
                        requester_email=requester.email,
                        approver_name=user.full_name or user.email,
                        prompt_key=prompt.key,
                        version_num=v.version_num,
                        env_name=env.name if env else "unknown"
                    )
        except Exception:
            pass
            
        return v

    async def reject_version(self, prompt_id: str, version_id: str, reason: str, user: User, member: OrgMember):
        """Reject a version and notify the requester."""
        v = self.db.query(PromptVersion).filter(
            PromptVersion.id == version_id, PromptVersion.prompt_id == prompt_id
        ).first()
        if not v:
            raise HTTPException(status_code=404, detail="Not found")
            
        v.status = "rejected"
        v.rejected_by_id = user.id
        v.rejection_reason = reason
        
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        self._log_action(
            org_id=member.org_id, user_id=user.id, user_email=user.email,
            action="version.rejected", resource_type="version", resource_id=v.id,
            extra={"reason": reason, "prompt_key": prompt.key if prompt else ""}
        )
        self.db.commit()
        
        # Notify Requester
        try:
            from app.core.email import send_version_rejected
            from app.config import get_settings
            if v.proposed_by_id:
                requester = self.db.query(User).filter(User.id == v.proposed_by_id).first()
                if requester:
                    await send_version_rejected(
                        requester_email=requester.email,
                        reviewer_name=user.full_name or user.email,
                        prompt_key=prompt.key if prompt else "",
                        version_num=v.version_num,
                        reason=reason,
                        dashboard_url=get_settings().app_url
                    )
        except Exception:
            pass
            
        return v

    def _log_action(self, org_id: str, user_id: str, user_email: str, action: str, 
                    resource_type: str, resource_id: str, extra: dict = None):
        """Create a secure audit log entry."""
        ts = datetime.now(timezone.utc)
        log = AuditLog(
            org_id=org_id,
            actor_id=user_id,
            actor_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            extra=extra or {},
            created_at=ts,
            integrity_hash=self._generate_integrity_hash(action, resource_id, ts)
        )
        self.db.add(log)

    def create_prompt(self, env_id: str, key: str, content: str, user_id: str, 
                      user_email: str, org_id: str, description: str = "", 
                      commit_message: str = "Initial version", tags: list = None) -> Prompt:
        """Create a new prompt and its first draft version."""
        # 1. Check if key exists
        if self.db.query(Prompt).filter(Prompt.environment_id == env_id, Prompt.key == key).first():
            raise HTTPException(status_code=409, detail="Key exists in this environment")

        # 2. Create Prompt
        prompt = Prompt(
            environment_id=env_id,
            key=key,
            description=description,
            tags=tags or [],
        )
        self.db.add(prompt)
        self.db.flush()

        # 3. Create initial version with safety checks
        content_safe = redact_identified_secrets(content)
        risks = analyze_prompt_safety(content)
        
        variables = self._detect_variables(content_safe)
        
        v = PromptVersion(
            prompt_id=prompt.id,
            version_num=1,
            content=content_safe,
            commit_message=commit_message,
            variables=variables,
            status="draft",
            proposed_by_id=user_id,
            approval_note=f"Policy Check: {len(risks)} risks detected." if risks else "Policy Check: Pass.",
        )
        self.db.add(v)
        
        # 4. Audit Log
        self._log_action(
            org_id=org_id, user_id=user_id, user_email=user_email,
            action="prompt.created", resource_type="prompt", resource_id=prompt.id,
            extra={"key": key, "env_id": env_id, "policy_risks": [r[0] for r in risks]}
        )
        
        self.db.commit()
        self.db.refresh(prompt)
        return prompt

    def create_version(self, prompt_id: str, content: str, user_id: str, 
                       user_email: str, org_id: str, commit_message: str = "") -> PromptVersion:
        """Create a new draft version for an existing prompt."""
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        parent_content = None
        if prompt.live_version_id:
            live = self.db.query(PromptVersion).filter(PromptVersion.id == prompt.live_version_id).first()
            if live:
                parent_content = live.content

        # Handle version number race condition with retries
        for attempt in range(3):
            try:
                vnum = self._get_next_version_num(prompt_id)
                content_safe = redact_identified_secrets(content)
                v = PromptVersion(
                    prompt_id=prompt_id,
                    version_num=vnum,
                    content=content_safe,
                    commit_message=commit_message or f"Version {vnum}",
                    variables=self._detect_variables(content_safe),
                    status="draft",
                    proposed_by_id=user_id,
                    parent_content=parent_content,
                )
                self.db.add(v)
                self.db.flush()
                break
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise HTTPException(status_code=409, detail="Concurrent version creation conflict")
                continue

        self._log_action(
            org_id=org_id, user_id=user_id, user_email=user_email,
            action="version.created", resource_type="version", resource_id=v.id,
            extra={"prompt_key": prompt.key, "version_num": vnum}
        )
        self.db.commit()
        self.db.refresh(v)
        return v

    async def rollback_prompt(self, prompt_id: str, version_id: str, user_id: str, user_email: str, org_id: str):
        """Roll back to a specific version by creating a new approved version from it."""
        prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        target = self.db.query(PromptVersion).filter(
            PromptVersion.id == version_id, PromptVersion.prompt_id == prompt_id
        ).first()

        if not prompt or not target:
            raise HTTPException(status_code=404, detail="Prompt or version not found")

        # Use retry loop for version number race condition
        for attempt in range(3):
            try:
                vnum = self._get_next_version_num(prompt_id)
                rollback_v = PromptVersion(
                    prompt_id=prompt_id,
                    version_num=vnum,
                    content=target.content,
                    commit_message=f"Rollback to v{target.version_num}",
                    variables=target.variables,
                    status="approved",
                    proposed_by_id=user_id,
                    approved_by_id=user_id,
                    approved_at=datetime.now(timezone.utc),
                    parent_content=prompt.live_version.content if prompt.live_version else None,
                )
                self.db.add(rollback_v)
                self.db.flush()
                break
            except IntegrityError:
                self.db.rollback()
                if attempt == 2:
                    raise HTTPException(status_code=409, detail="Concurrent version creation conflict")
                continue

        # Update prompt live version with optimistic locking
        prompt.live_version_id = rollback_v.id
        self._apply_optimistic_lock(prompt)

        await invalidate_prompt_cache(prompt.environment_id, prompt.key)

        self._log_action(
            org_id=org_id, user_id=user_id, user_email=user_email,
            action="version.rollback", resource_type="version", resource_id=rollback_v.id,
            extra={"rolled_back_to": target.version_num, "new_version": vnum, "prompt_key": prompt.key}
        )
        self.db.commit()
        return rollback_v

    async def promote_prompt(self, prompt_id: str, target_env_id: str, user_id: str, 
                       user_email: str, org_id: str, auto_approve: bool = False):
        """Handle promotion from one environment to another. Formalizes with PromotionRequest."""
        from app.models import PromotionRequest
        
        source_prompt = self.db.query(Prompt).filter(Prompt.id == prompt_id).first()
        if not source_prompt or not source_prompt.live_version_id:
            raise HTTPException(status_code=404, detail="Source prompt has no live version to promote")
        
        live_v = self.db.query(PromptVersion).filter(PromptVersion.id == source_prompt.live_version_id).first()
        
        # 1. Create Promotion Request (Record)
        request = PromotionRequest(
            org_id=org_id,
            prompt_id=prompt_id,
            source_env_id=source_prompt.environment_id,
            target_env_id=target_env_id,
            version_num=live_v.version_num,
            status="pending",
            created_by_id=user_id,
            notes=f"Promotion from {source_prompt.key} (v{live_v.version_num})"
        )
        self.db.add(request)
        self.db.flush()

        # 2. Logic for execution (Auto-approve in dev, or just create draft in prod)
        # Find or create prompt in target env
        target_prompt = self.db.query(Prompt).filter(
            Prompt.environment_id == target_env_id,
            Prompt.key == source_prompt.key
        ).first()

        if not target_prompt:
            target_prompt = Prompt(
                environment_id=target_env_id,
                key=source_prompt.key,
                description=source_prompt.description,
                tags=source_prompt.tags,
            )
            self.db.add(target_prompt)
            self.db.flush()

        # 3. Create the new version in target env
        vnum = self._get_next_version_num(target_prompt.id)
        from app.config import get_settings
        is_dev = get_settings().app_env == "development"
        
        status = "approved" if (auto_approve and is_dev) else "draft"
        
        new_v = PromptVersion(
            prompt_id=target_prompt.id,
            version_num=vnum,
            content=live_v.content,
            commit_message=f"Promoted from v{live_v.version_num}",
            variables=live_v.variables,
            status=status,
            proposed_by_id=user_id,
        )
        if status == "approved":
            new_v.approved_by_id = user_id
            new_v.approved_at = datetime.now(timezone.utc)
            target_prompt.live_version_id = new_v.id
            self._apply_optimistic_lock(target_prompt)
            await invalidate_prompt_cache(target_env_id, target_prompt.key)
            request.status = "executed"
            request.executed_at = datetime.now(timezone.utc)
            request.approved_by_id = user_id

        self.db.add(new_v)
        
        self._log_action(
            org_id=org_id, user_id=user_id, user_email=user_email,
            action="prompt.promoted", resource_type="prompt", resource_id=target_prompt.id,
            extra={"from_prompt_id": source_prompt.id, "target_env": target_env_id, "status": status}
        )
        self.db.commit()
        return target_prompt, new_v

    def _apply_optimistic_lock(self, prompt: Prompt):
        """Manually increment the version counter to trigger optimistic locking."""
        prompt.version += 1
        prompt.updated_at = datetime.now(timezone.utc)

    def _get_next_version_num(self, prompt_id: str) -> int:
        result = self.db.query(func.max(PromptVersion.version_num)).filter(
            PromptVersion.prompt_id == prompt_id
        ).scalar()
        return (result + 1) if result is not None else 1

    def _detect_variables(self, content: str) -> dict:
        found = re.findall(r'\{\{([\w_]+)\}\}', content)
        return {v: "" for v in set(found)}

