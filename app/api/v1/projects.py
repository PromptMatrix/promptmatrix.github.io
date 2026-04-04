"""
Projects + Environments — /api/v1/projects
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_and_org
from app.database import get_db
from app.models import Environment, Project, Prompt, PromptVersion

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("")
async def list_projects(
    auth=Depends(get_current_user_and_org), db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org context")

    projects = db.query(Project).filter(Project.org_id == member.org_id).all()

    result = []
    for p in projects:
        envs = db.query(Environment).filter(Environment.project_id == p.id).all()
        result.append(
            {
                "id": p.id,
                "name": p.name,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "environments": [
                    {
                        "id": e.id,
                        "name": e.name,
                        "display_name": e.display_name,
                        "color": e.color,
                        "is_protected": e.is_protected,
                        "eval_pass_threshold": e.eval_pass_threshold,
                    }
                    for e in envs
                ],
            }
        )

    return {"projects": result}


@router.get("/export")
async def export_workspace(
    auth=Depends(get_current_user_and_org), db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org context")

    # Fetch all data for the organisation
    projects = db.query(Project).filter(Project.org_id == member.org_id).all()

    export_data = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organisation": {
            "name": member.org.name,
            "slug": member.org.slug,
        },
        "projects": [],
    }

    for p in projects:
        envs = db.query(Environment).filter(Environment.project_id == p.id).all()
        p_data = {"name": p.name, "environments": []}
        for e in envs:
            prompts = db.query(Prompt).filter(Prompt.environment_id == e.id).all()
            e_data = {
                "name": e.name,
                "display_name": e.display_name,
                "color": e.color,
                "is_protected": e.is_protected,
                "eval_pass_threshold": e.eval_pass_threshold,
                "prompts": [],
            }
            for pr in prompts:
                versions = (
                    db.query(PromptVersion)
                    .filter(PromptVersion.prompt_id == pr.id)
                    .all()
                )
                pr_data = {
                    "key": pr.key,
                    "description": pr.description,
                    "tags": pr.tags,
                    "versions": [],
                }
                for v in versions:
                    pr_data["versions"].append(
                        {
                            "version_num": v.version_num,
                            "content": v.content,
                            "commit_message": v.commit_message,
                            "status": v.status,
                            "variables": v.variables,
                            "approval_note": v.approval_note,
                            "is_live": v.id == pr.live_version_id,
                        }
                    )
                e_data["prompts"].append(pr_data)
            p_data["environments"].append(e_data)
        export_data["projects"].append(p_data)

    return export_data


@router.post("/import")
async def import_workspace(
    body: dict, auth=Depends(get_current_user_and_org), db: Session = Depends(get_db)
):
    user, member = auth
    if not member:
        raise HTTPException(status_code=403, detail="No org context")
    from app.core.auth import require_role

    require_role(member, "admin")

    # Basic validation
    if "projects" not in body:
        raise HTTPException(status_code=400, detail="Invalid export format")

    import_count = 0
    for p_data in body["projects"]:
        # Find or create project
        project = (
            db.query(Project)
            .filter(Project.org_id == member.org_id, Project.name == p_data["name"])
            .first()
        )
        if not project:
            project = Project(org_id=member.org_id, name=p_data["name"])
            db.add(project)
            db.flush()

        for e_data in p_data.get("environments", []):
            # Find or create environment
            env = (
                db.query(Environment)
                .filter(
                    Environment.project_id == project.id,
                    Environment.name == e_data["name"],
                )
                .first()
            )
            if not env:
                env = Environment(
                    project_id=project.id,
                    name=e_data["name"],
                    display_name=e_data.get("display_name", ""),
                    color=e_data.get("color", "#888888"),
                    is_protected=e_data.get("is_protected", True),
                    eval_pass_threshold=e_data.get("eval_pass_threshold", 7.0),
                )
                db.add(env)
                db.flush()

            for pr_data in e_data.get("prompts", []):
                # Find or create prompt
                prompt = (
                    db.query(Prompt)
                    .filter(
                        Prompt.environment_id == env.id, Prompt.key == pr_data["key"]
                    )
                    .first()
                )
                if not prompt:
                    prompt = Prompt(
                        environment_id=env.id,
                        key=pr_data["key"],
                        description=pr_data.get("description", ""),
                        tags=pr_data.get("tags", []),
                    )
                    db.add(prompt)
                    db.flush()

                for v_data in pr_data.get("versions", []):
                    # check if version exists
                    existing_v = (
                        db.query(PromptVersion)
                        .filter(
                            PromptVersion.prompt_id == prompt.id,
                            PromptVersion.version_num == v_data["version_num"],
                        )
                        .first()
                    )
                    if not existing_v:
                        new_v = PromptVersion(
                            prompt_id=prompt.id,
                            version_num=v_data["version_num"],
                            content=v_data["content"],
                            commit_message=v_data.get("commit_message", ""),
                            status=v_data.get("status", "draft"),
                            variables=v_data.get("variables", {}),
                            proposed_by_id=user.id,
                            approval_note=v_data.get("approval_note", ""),
                        )
                        db.add(new_v)
                        db.flush()
                        if v_data.get("is_live"):
                            prompt.live_version_id = new_v.id
                        import_count += 1

    db.commit()
    from app.models import AuditLog

    db.add(
        AuditLog(
            org_id=member.org_id,
            actor_id=user.id,
            actor_email=user.email,
            action="workspace.imported",
            resource_type="workspace",
            resource_id=member.org_id,
            extra={"imported_versions": import_count},
        )
    )
    db.commit()
    return {"message": f"Imported {import_count} versions successfully"}
