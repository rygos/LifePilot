from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Project, User
from lifepilot.schemas import ProjectIn, ProjectOut, ProjectPatch
from lifepilot.security import current_user
from lifepilot.services import project_create as create_project, project_get, project_list as list_projects, project_update as update_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def project_list(db: Session = Depends(get_db), user: User = Depends(current_user), q: str = ""):
    return list_projects(db, user, q)


@router.post("", response_model=ProjectOut, status_code=201)
def project_create(data: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return create_project(db, user, data)

@router.get("/{project_id}", response_model=ProjectOut)
def project_get_route(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return project_get(db, user, project_id)

@router.patch("/{project_id}", response_model=ProjectOut)
def project_update(project_id: str, data: ProjectPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return update_project(db, user, project_id, data)


@router.delete("/{project_id}", status_code=204)
def project_delete(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="projects", resource_id=project.id, source="web"))
    db.delete(project)
    db.commit()
