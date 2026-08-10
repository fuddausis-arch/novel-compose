"""自定义工作流 API：用户通过可视化编辑器创建的工作流。

custom_workflows 表存储完整工作流定义（workflow_json），
工作流加载器在加载时会合并内置 YAML 工作流和数据库自定义工作流。
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, CustomWorkflow
from novel_agent.config import load_config

router = APIRouter()
logger = logging.getLogger(__name__)


def get_db():
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===== Pydantic 输入 =====
class CustomWorkflowInput(BaseModel):
    workflow_id: str          # 用户定义的唯一 ID（如 my-build-v2）
    name: str
    description: str = ""
    workflow_json: dict       # 完整工作流定义（nodes/edges/start_position/inputs/agent_role）


class CustomWorkflowUpdateInput(BaseModel):
    name: str | None = None
    description: str | None = None
    workflow_json: dict | None = None


# ===== 序列化 =====
def _workflow_dict(w: CustomWorkflow) -> dict:
    return {
        "id": w.id,
        "project_id": w.project_id,
        "workflow_id": w.workflow_id,
        "name": w.name,
        "description": w.description,
        "workflow_json": w.workflow_json or {},
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


# ===== 辅助：同时支持数字 id 和字符串 workflow_id 查找 =====
def _find_workflow(db: Session, project_id: int, identifier: str) -> CustomWorkflow | None:
    """先按字符串 workflow_id 查找，再尝试按数字 id 查找。"""
    w = db.query(CustomWorkflow).filter(
        CustomWorkflow.project_id == project_id,
        CustomWorkflow.workflow_id == identifier,
    ).first()
    if w:
        return w
    # 尝试数字 id
    try:
        num_id = int(identifier)
        return db.query(CustomWorkflow).filter(
            CustomWorkflow.project_id == project_id,
            CustomWorkflow.id == num_id,
        ).first()
    except (ValueError, TypeError):
        return None


# ===== CRUD =====
@router.get("/{project_id}/custom-workflows")
def list_custom_workflows(project_id: int, db: Session = Depends(get_db)):
    items = db.query(CustomWorkflow).filter(CustomWorkflow.project_id == project_id).order_by(CustomWorkflow.updated_at.desc()).all()
    return [_workflow_dict(w) for w in items]


@router.get("/{project_id}/custom-workflows/{workflow_id}")
def get_custom_workflow(project_id: int, workflow_id: str, db: Session = Depends(get_db)):
    w = _find_workflow(db, project_id, workflow_id)
    if not w:
        raise HTTPException(404, "自定义工作流不存在")
    return _workflow_dict(w)


@router.post("/{project_id}/custom-workflows")
def create_custom_workflow(project_id: int, data: CustomWorkflowInput, db: Session = Depends(get_db)):
    if not data.workflow_id.strip():
        raise HTTPException(400, "workflow_id 不能为空")
    if not data.name.strip():
        raise HTTPException(400, "工作流名称不能为空")
    existing = db.query(CustomWorkflow).filter(
        CustomWorkflow.project_id == project_id,
        CustomWorkflow.workflow_id == data.workflow_id.strip(),
    ).first()
    if existing:
        raise HTTPException(409, "workflow_id 已存在")
    w = CustomWorkflow(
        project_id=project_id,
        workflow_id=data.workflow_id.strip(),
        name=data.name.strip(),
        description=data.description,
        workflow_json=data.workflow_json,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return _workflow_dict(w)


@router.put("/{project_id}/custom-workflows/{workflow_id}")
def update_custom_workflow(project_id: int, workflow_id: str, data: CustomWorkflowUpdateInput, db: Session = Depends(get_db)):
    w = _find_workflow(db, project_id, workflow_id)
    if not w:
        raise HTTPException(404, "自定义工作流不存在")
    if data.name is not None:
        w.name = data.name.strip()
    if data.description is not None:
        w.description = data.description
    if data.workflow_json is not None:
        w.workflow_json = data.workflow_json
    db.commit()
    db.refresh(w)
    return _workflow_dict(w)


@router.delete("/{project_id}/custom-workflows/{workflow_id}")
def delete_custom_workflow(project_id: int, workflow_id: str, db: Session = Depends(get_db)):
    w = _find_workflow(db, project_id, workflow_id)
    if not w:
        raise HTTPException(404, "自定义工作流不存在")
    db.delete(w)
    db.commit()
    return {"deleted": True}
