"""参考文件管理 API：上传/列表/删除/读取项目级参考文档。

上传的文件持久化存储在 project_data/projects/{id}/references/，
供 Chat 对话和章节生成时作为参考资料注入上下文。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from novel_agent.config import load_config
from novel_agent.utils.file_extract import extract_text_or_image, MAX_UPLOAD_SIZE

logger = logging.getLogger(__name__)
router = APIRouter()


class ReferenceFileItem(BaseModel):
    filename: str
    size: int
    content_preview: str


def _get_references_dir(project_id: int) -> Path:
    cfg = load_config()
    ref_dir = cfg.project_dir(project_id) / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    return ref_dir


@router.get("/{project_id}/references", response_model=list[ReferenceFileItem])
async def list_references(project_id: int):
    """列出项目所有参考文件。"""
    ref_dir = _get_references_dir(project_id)
    items = []
    for f in sorted(ref_dir.iterdir()):
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        items.append(ReferenceFileItem(
            filename=f.name,
            size=f.stat().st_size,
            content_preview=content[:500],
        ))
    return items


@router.get("/{project_id}/references/{filename}")
async def get_reference(project_id: int, filename: str):
    """读取单个参考文件的完整内容。"""
    ref_dir = _get_references_dir(project_id)
    safe_name = Path(filename).name  # 防止路径穿越
    filepath = ref_dir / safe_name
    if not filepath.exists():
        raise HTTPException(404, f"参考文件 {filename} 不存在")
    content = filepath.read_text(encoding="utf-8", errors="replace")
    return {"filename": safe_name, "content": content, "size": filepath.stat().st_size}


@router.post("/{project_id}/references")
async def upload_reference(project_id: int, file: UploadFile = File(...)):
    """上传参考文件，持久化存储到项目目录。

    支持文本类（txt/md/json/csv/html 等）和文档类（docx/pdf）。
    提取为纯文本后保存，方便后续注入 Chat 上下文。
    """
    content_bytes = await file.read()
    if len(content_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"文件过大（{len(content_bytes)} bytes），最大允许 {MAX_UPLOAD_SIZE} bytes")

    original_name = file.filename or "untitled.txt"
    safe_name = Path(original_name).name
    # 去掉扩展名，存为 .txt 方便后续读取
    stem = Path(safe_name).stem
    save_name = f"{stem}.txt"

    ref_dir = _get_references_dir(project_id)

    # 避免重名
    counter = 1
    while (ref_dir / save_name).exists():
        save_name = f"{stem}_{counter}.txt"
        counter += 1

    # 提取文本内容
    from novel_agent.utils.file_extract import _extract_text_plain, _extract_docx, _extract_pdf
    suffix = Path(safe_name).suffix.lower()
    try:
        if suffix == ".docx":
            text = _extract_docx(content_bytes)
        elif suffix == ".pdf":
            text = _extract_pdf(content_bytes)
        else:
            text = _extract_text_plain(content_bytes)
    except Exception as e:
        logger.warning("参考文件 %s 提取失败，降级为原始字节: %s", safe_name, e)
        text = _extract_text_plain(content_bytes)

    filepath = ref_dir / save_name
    filepath.write_text(text, encoding="utf-8")

    # 向量化入库，供 Writer 语义检索
    try:
        from novel_agent.bible.database import get_config
        from novel_agent.memory.archival import ArchivalMemory
        cfg = get_config()
        if cfg and (cfg.embedding_api_key or cfg.embedding_model):
            archival = ArchivalMemory(cfg, project_id=project_id)
            archival.index_reference(filename=save_name, content=text)
    except Exception as e:
        logger.warning("参考文档向量化失败（不影响上传）: %s", e)

    logger.info("参考文件已保存: %s (project=%d, %d 字符)", save_name, project_id, len(text))
    return {
        "filename": save_name,
        "original_name": safe_name,
        "size": filepath.stat().st_size,
        "char_count": len(text),
        "content_preview": text[:500],
    }


@router.delete("/{project_id}/references/{filename}")
async def delete_reference(project_id: int, filename: str):
    """删除参考文件。"""
    ref_dir = _get_references_dir(project_id)
    safe_name = Path(filename).name
    filepath = ref_dir / safe_name
    if not filepath.exists():
        raise HTTPException(404, f"参考文件 {filename} 不存在")
    filepath.unlink()

    # 从向量库删除该文件的所有片段
    try:
        from novel_agent.bible.database import get_config
        from novel_agent.memory.archival import ArchivalMemory
        cfg = get_config()
        if cfg:
            archival = ArchivalMemory(cfg, project_id=project_id)
            coll = archival._get_collection("references")
            results = coll.get(where={"filename": safe_name})
            if results and results.get("ids"):
                coll.delete(ids=results["ids"])
    except Exception as e:
        logger.warning("参考文档向量删除失败: %s", e)

    return {"deleted": True, "filename": safe_name}


def get_all_reference_text(project_id: int) -> str:
    """读取项目所有参考文件内容，拼接为一个字符串。

    供 Chat 上下文注入使用。
    """
    ref_dir = _get_references_dir(project_id)
    parts = []
    for f in sorted(ref_dir.iterdir()):
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            if content.strip():
                parts.append(f"【参考文件：{f.name}】\n{content}")
        except Exception:
            continue
    return "\n\n".join(parts)
