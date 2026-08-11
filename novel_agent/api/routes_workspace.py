"""工作区管理后端：会话树/子会话 + 附件管理 + 文件管理。

借鉴 DeterminFlow 的会话树和附件管理：
- 会话树：主会话 -> 子会话（分支讨论）
- 附件上传：图片/文档
- 工作区文件浏览：项目目录文件列表

会话树关系用轻量 JSON 文件存储（不修改现有 DB 模型），
附件存储在项目目录的 attachments/ 子目录下。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from novel_agent.api.app import limiter
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, ChatSession
from novel_agent.config import load_config

logger = logging.getLogger(__name__)
router = APIRouter()

# 允许浏览的文件扩展名（安全白名单）
_ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".yaml", ".yml",
    ".py", ".js", ".ts", ".html", ".css",
}
# 附件最大大小（100MB）
_MAX_ATTACHMENT_SIZE = 100 * 1024 * 1024


def _setup_db():
    """初始化数据库连接。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    return SessionLocal()


def _session_tree_path(project_id: int) -> Path:
    """获取项目会话树 JSON 文件路径。"""
    cfg = load_config()
    pdir = cfg.project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir / "session_tree.json"


def _load_session_tree(project_id: int) -> dict[str, str]:
    """加载会话树映射（parent_session_id -> child_session_id 的反向映射）。"""
    tree_path = _session_tree_path(project_id)
    if not tree_path.exists():
        return {}
    try:
        return json.loads(tree_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_session_tree(project_id: int, tree: dict[str, str]) -> None:
    """保存会话树映射。"""
    tree_path = _session_tree_path(project_id)
    tree_path.write_text(
        json.dumps(tree, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _attachments_dir(project_id: int, session_id: str = "") -> Path:
    """获取附件目录路径。"""
    cfg = load_config()
    pdir = cfg.project_dir(project_id) / "attachments"
    if session_id:
        pdir = pdir / session_id
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir


# ── 请求/响应模型 ─────────────────────────────────────────────

class BranchRequest(BaseModel):
    """创建子会话请求。"""
    project_id: int
    parent_session_id: str
    title: str = ""


class BranchResponse(BaseModel):
    """创建子会话响应。"""
    session_id: str
    parent_session_id: str
    title: str


# ── 会话树端点 ─────────────────────────────────────────────────

@router.get("/sessions/{project_id}/tree")
@limiter.limit("30/minute")
async def get_session_tree(request: Request, project_id: int):
    """获取项目的会话树。

    返回主会话列表，每个主会话可包含子会话（分支讨论）。
    """
    db = _setup_db()
    try:
        # 查询项目所有会话
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.project_id == project_id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        # 加载会话树映射
        tree = _load_session_tree(project_id)
        # child_id -> parent_id 的映射，反转得到 parent_id -> [child_ids]
        children_map: dict[str, list[str]] = {}
        for child_id, parent_id in tree.items():
            children_map.setdefault(parent_id, []).append(child_id)

        # 构建会话树
        session_map = {s.id: s for s in sessions}
        result: list[dict[str, Any]] = []
        for s in sessions:
            # 只在树中存在的子会话不作为顶层节点
            if s.id in tree:
                continue
            node: dict[str, Any] = {
                "id": s.id,
                "title": s.title,
                "session_type": s.session_type,
                "object_type": s.object_type,
                "object_id": s.object_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "children": [],
            }
            # 递归添加子会话
            for child_id in children_map.get(s.id, []):
                child = session_map.get(child_id)
                if child:
                    node["children"].append({
                        "id": child.id,
                        "title": child.title,
                        "session_type": child.session_type,
                        "object_type": child.object_type,
                        "object_id": child.object_id,
                        "created_at": child.created_at.isoformat() if child.created_at else None,
                        "updated_at": child.updated_at.isoformat() if child.updated_at else None,
                    })
            result.append(node)
        return {"sessions": result}
    finally:
        db.close()


@router.post("/sessions/{session_id}/branch")
@limiter.limit("20/minute")
async def create_branch_session(request: Request, session_id: str, req: BranchRequest):
    """创建子会话（分支讨论）。

    在现有会话下创建一个子会话，用于分支讨论。
    子会话继承父会话的 project_id 和 session_type。
    """
    db = _setup_db()
    try:
        # 查找父会话
        parent = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id)
            .first()
        )
        if not parent:
            raise HTTPException(404, "父会话不存在")

        # 创建子会话
        child = ChatSession(
            id=str(uuid.uuid4()),
            project_id=parent.project_id,
            session_type=parent.session_type,
            object_type=parent.object_type,
            object_id=parent.object_id,
            title=req.title or f"分支-{session_id[:8]}",
        )
        db.add(child)
        db.commit()
        db.refresh(child)

        # 记录会话树关系
        tree = _load_session_tree(parent.project_id)
        tree[child.id] = parent.id
        _save_session_tree(parent.project_id, tree)

        return BranchResponse(
            session_id=child.id,
            parent_session_id=parent.id,
            title=child.title,
        )
    finally:
        db.close()


# ── 附件管理端点 ───────────────────────────────────────────────

@router.post("/attachments")
@limiter.limit("10/minute")
async def upload_attachment(
    request: Request,
    project_id: int,
    session_id: str,
    file: UploadFile = File(...),
):
    """上传附件到指定会话。

    支持 图片/文档 等文件类型，最大 10MB。
    """
    # 检查文件大小
    content = await file.read()
    if len(content) > _MAX_ATTACHMENT_SIZE:
        raise HTTPException(413, f"附件大小超过限制（{_MAX_ATTACHMENT_SIZE // 1024 // 1024}MB）")

    # 安全文件名（防路径穿越）
    safe_name = Path(file.filename or "unnamed").name
    if not safe_name or safe_name.startswith("."):
        safe_name = f"attachment_{uuid.uuid4().hex[:8]}"

    attach_dir = _attachments_dir(project_id, session_id)
    file_path = attach_dir / safe_name
    file_path.write_bytes(content)

    logger.info("附件已上传: project=%s session=%s file=%s", project_id, session_id, safe_name)
    return {
        "status": "uploaded",
        "filename": safe_name,
        "size": len(content),
        "session_id": session_id,
    }


@router.get("/attachments/{session_id}")
@limiter.limit("30/minute")
async def get_attachments(request: Request, session_id: str, project_id: int = 0):
    """获取会话的附件列表。"""
    if project_id == 0:
        raise HTTPException(400, "project_id 不能为空")
    attach_dir = _attachments_dir(project_id, session_id)
    if not attach_dir.exists():
        return {"attachments": []}
    attachments: list[dict[str, Any]] = []
    for f in sorted(attach_dir.iterdir()):
        if not f.is_file():
            continue
        stat = f.stat()
        attachments.append({
            "filename": f.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return {"attachments": attachments}


# ── 工作区文件管理端点 ─────────────────────────────────────────

@router.get("/files")
@limiter.limit("30/minute")
async def list_workspace_files(
    request: Request,
    project_id: int = 0,
    subpath: str = "",
):
    """列出工作区文件。

    浏览项目目录下的文件，仅返回白名单扩展名的文件。
    """
    cfg = load_config()
    if project_id > 0:
        base_dir = cfg.project_dir(project_id)
    else:
        base_dir = cfg.project_data_dir

    # 安全：防路径穿越
    target = base_dir
    if subpath:
        safe_sub = Path(subpath).as_posix().lstrip("/")
        target = (base_dir / safe_sub).resolve()
        try:
            target.relative_to(base_dir.resolve())
        except ValueError:
            raise HTTPException(403, "路径越权访问")

    if not target.exists() or not target.is_dir():
        return {"files": [], "path": str(subpath)}

    files: list[dict[str, Any]] = []
    for f in sorted(target.iterdir()):
        rel = f.relative_to(base_dir).as_posix()
        if f.is_dir():
            files.append({"name": f.name, "type": "dir", "size": 0, "path": rel})
        elif f.is_file():
            ext = f.suffix.lower()
            if ext in _ALLOWED_EXTENSIONS:
                files.append({
                    "name": f.name,
                    "type": "file",
                    "size": f.stat().st_size,
                    "ext": ext,
                    "path": rel,
                })
    return {"files": files, "path": str(subpath), "base": str(base_dir)}


@router.get("/files/{path:path}")
@limiter.limit("30/minute")
async def read_workspace_file(
    request: Request,
    path: str,
    project_id: int = 0,
):
    """读取工作区文件内容。

    仅允许读取白名单扩展名的文件，防路径穿越。
    """
    cfg = load_config()
    if project_id > 0:
        base_dir = cfg.project_dir(project_id)
    else:
        base_dir = cfg.project_data_dir

    # 安全：防路径穿越
    safe_path = Path(path).as_posix().lstrip("/")
    target = (base_dir / safe_path).resolve()
    try:
        target.relative_to(base_dir.resolve())
    except ValueError:
        raise HTTPException(403, "路径越权访问")

    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")

    ext = target.suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(403, f"不允许读取 {ext} 类型的文件")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(500, f"读取文件失败: {e}")

    return {
        "filename": target.name,
        "path": str(safe_path),
        "content": content,
        "size": len(content),
    }
