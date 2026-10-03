"""Persisted coach reads do not contact Gitea or model providers."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.responses import ok
from app.api.endpoints.team_git import resolve_team_git_actor, TeamGitRoute
from app.services.team_git_service import require_project_action, _project_visible_to_actor, MODULE, PROJECT
from app.repositories.json_store import JsonStore
from app.services.git_coach_jobs import list_coach, retry_job, schema_ready, worker_enabled

router = APIRouter(route_class=TeamGitRoute)


def _coach_project(db, project_id, actor):
    # No _load_project/enrichment: those legacy paths may normalize or fetch Gitea.
    with db.no_autoflush:
        project = JsonStore(db).get_payload(MODULE, PROJECT, project_id)
    if project is None:
        raise HTTPException(404, 'project_not_found')
    if not _project_visible_to_actor(project, actor):
        raise HTTPException(403, 'project_access_denied')
    return project


def _require_schema(db):
    if not schema_ready(db.get_bind()):
        raise HTTPException(503, {'code': 'coach_schema_unavailable', 'schemaReady': False,
                                 'workerEnabled': worker_enabled()})


@router.get('/team-git/coach-health')
def coach_health(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    resolve_team_git_actor(authorization, db)
    return ok({'schemaReady': schema_ready(db.get_bind()), 'workerEnabled': worker_enabled()})


@router.get('/team-git/projects/{project_id}/coach')
def get_coach(project_id: str, limit: int = Query(20, ge=1, le=100),
              before: int | None = Query(None, ge=1), authorization: str | None = Header(None),
              db: Session = Depends(get_db)):
    actor = resolve_team_git_actor(authorization, db)
    _coach_project(db, project_id, actor)
    _require_schema(db)
    return ok(list_coach(db, project_id, limit=limit, before=before))


@router.post('/team-git/projects/{project_id}/coach/jobs/{job_id}/retry')
def retry_coach(project_id: str, job_id: str, authorization: str | None = Header(None),
                db: Session = Depends(get_db)):
    actor = resolve_team_git_actor(authorization, db)
    project = _coach_project(db, project_id, actor)
    try:
        require_project_action(project, actor, action='manage')
        _require_schema(db)
        return ok(retry_job(db, project_id, job_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
