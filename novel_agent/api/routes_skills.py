"""Skills 管理后端：CRUD + 热重载 + 分层加载。

借鉴 DeterminFlow skills/ 模块：
- Skill 定义：name, description, sections (prompt section), tools, enabled
- 渐进式披露三阶段：Discovery -> Activation -> Execution
- 分层加载：core -> plugin -> user（后者覆盖前者）

数据存储：project_data/skills/ 目录，每个 skill 一个 JSON 文件。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import asyncio
import json as _json

from novel_agent.config import load_config

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- Pydantic 模型 ----


class SkillSection(BaseModel):
    """Skill 的 prompt section 定义。"""
    name: str
    content: str


class SkillBase(BaseModel):
    """Skill 基础字段（创建/更新共用）。"""
    name: str
    description: str = ""
    enabled: bool = True
    auto_inject: bool = True  # 默认自动注入：启用即参与每次生成注入
    sections: list[SkillSection] = []
    tools: list[str] = []
    references: list[str] = []


class SkillUpdate(BaseModel):
    """Skill 更新字段（name 可选，传了则重命名）。"""
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    auto_inject: bool | None = None
    sections: list[SkillSection] | None = None
    tools: list[str] | None = None
    references: list[str] | None = None


# ---- 文件 I/O 辅助 ----


def _skills_dir() -> Path:
    """获取 skills 存储目录，自动创建。"""
    cfg = load_config()
    d = cfg.project_data_dir / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _skill_path(name: str) -> Path:
    """获取单个 skill 的 JSON 文件路径。

    防止路径遍历：禁止路径分隔符、Windows 非法字符、控制字符、`.`/`..`。
    允许中文等任意安全字符（文件名层面），支持用户给 skill 起中文名。
    """
    name = name.strip()
    if not name:
        raise HTTPException(400, "skill 名称不能为空")
    if name in (".", ".."):
        raise HTTPException(400, "无效的 skill 名称")
    if any(ord(ch) < 32 or ch in '/\\:*?"<>|' for ch in name):
        raise HTTPException(400, f"无效的 skill 名称（不能包含路径分隔符或特殊符号）: {name}")
    return _skills_dir() / f"{name}.json"


def _load_skill(name: str) -> dict:
    """读取单个 skill JSON，不存在时抛 404。"""
    path = _skill_path(name)
    if not path.exists():
        raise HTTPException(404, f"Skill 不存在: {name}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # 旧数据无 auto_inject 字段时按 True 处理（默认自动注入）
        data.setdefault("auto_inject", True)
        return data
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"读取 skill 失败: {e}")


def _save_skill(data: dict) -> None:
    """写入 skill JSON。"""
    path = _skill_path(data["name"])
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存 skill 失败: {e}")


# ---- 端点 ----


# ---- 默认 Skill 资产（DeterminFlow 内置 6 个 + writing-assistant）----

_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "defaults" / "skills"


def _parse_skill_md(skill_md_path: Path) -> dict | None:
    """解析 SKILL.md 的 YAML frontmatter + 正文，转成 NovelAgent skill JSON 格式。

    DeterminFlow 的 Skill 是 SKILL.md 文件（YAML frontmatter + Markdown 正文），
    NovelAgent 的 Skill 是 JSON（name/description/enabled/sections/tools/references）。
    这里做一次格式转换，让前端管理页能看到这些内置 Skill。

    语料型 skill（frontmatter 含 source: corpus）的正文按 `## ` 标题拆成多个 section，
    供写作时按上下文检索相关条目（只注入命中的条目，不整库注入）；
    其余内置 skill 保持单 body section（向后兼容）。
    """
    import re
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # 解析 YAML frontmatter
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return None
    frontmatter, body = m.group(1), m.group(2)
    # 简单提取 name / description / source
    name = skill_md_path.parent.name
    description = ""
    source = ""
    fm_lines = frontmatter.split("\n")
    for idx, line in enumerate(fm_lines):
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            # 处理 >- 多行
            val = line.split(":", 1)[1].strip()
            if val.startswith(">-") or val == "":
                # 收集后续缩进行
                desc_lines = []
                for desc_line in fm_lines[idx + 1:]:
                    if desc_line.startswith("  "):
                        desc_lines.append(desc_line.strip())
                    else:
                        break
                description = " ".join(desc_lines)
            else:
                description = val.strip('"').strip("'")
        elif line.startswith("source:"):
            source = line.split(":", 1)[1].strip().strip('"').strip("'")

    # 语料型 skill：按 ## 标题拆多 section（content 保留标题行，检索与展示均可用）
    if source == "corpus":
        sections: list[dict] = []
        for sec in re.split(r"(?m)^(?=## )", body):
            sec = sec.strip()
            if not sec:
                continue
            sec_title = sec.split("\n", 1)[0].lstrip("#").strip()
            sections.append({"name": sec_title, "content": sec})
    else:
        sections = [{"name": "body", "content": body.strip()}]

    return {
        "name": name,
        "description": description,
        "enabled": True,
        "auto_inject": True,  # 内置 skill 默认自动注入
        "sections": sections,
        "tools": [],
        "references": [],
        "is_builtin": True,  # 标记为内置（前端不可删除/编辑）
        "source": source,
    }


def _list_default_skills() -> list[dict]:
    """加载 defaults/skills/ 下的所有内置 Skill。"""
    if not _DEFAULT_SKILLS_DIR.exists():
        return []
    result = []
    for skill_dir in sorted(_DEFAULT_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        parsed = _parse_skill_md(skill_md)
        if parsed:
            result.append(parsed)
    return result


def _seed_default_skills_if_empty() -> None:
    """首次启动时把内置 Skill 播种到 project_data/skills/ 目录。

    让用户能在前端看到并启用/禁用这些 Skill。
    只播种不存在的，不覆盖用户已有的。
    """
    d = _skills_dir()
    defaults = _list_default_skills()
    for skill in defaults:
        path = d / f"{skill['name']}.json"
        if not path.exists():
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(skill, f, ensure_ascii=False, indent=2)
            except OSError:
                pass


@router.get("")
def list_skills():
    """列出所有 skills（内置默认 + 用户自建）。"""
    # 首次启动播种内置 Skill
    _seed_default_skills_if_empty()
    d = _skills_dir()
    skills = []
    for p in sorted(d.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                skill = json.load(f)
            skill.setdefault("auto_inject", True)
            skills.append(skill)
        except (json.JSONDecodeError, OSError):
            continue  # 跳过损坏的文件
    return {"skills": skills}


class SkillBatchDelete(BaseModel):
    """批量删除请求体。"""
    names: list[str] = []


@router.post("/batch-delete")
def batch_delete_skills(req: SkillBatchDelete):
    """批量删除 skill（内置 Skill 不可删，逐条尝试，失败不阻塞其余）。

    必须在 /{name} 路由之前定义，否则 batch-delete 会被当 name 匹配。
    """
    names = [n.strip() for n in req.names if n.strip()]
    deleted: list[str] = []
    failed: list[dict] = []
    for name in names:
        path = _skill_path(name)
        if not path.exists():
            failed.append({"name": name, "error": "不存在"})
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("is_builtin"):
                failed.append({"name": name, "error": "内置 Skill 不可删除，可禁用"})
                continue
        except (json.JSONDecodeError, OSError):
            pass
        try:
            path.unlink()
            deleted.append(name)
        except OSError as e:
            failed.append({"name": name, "error": str(e)})
    if deleted:
        rebuild_skill_index()
    return {"deleted": deleted, "failed": failed, "deleted_count": len(deleted)}


@router.get("/search")
def search_skills(q: str = "", limit: int = 20, enabled_only: bool = False):
    """跨 skill 统一搜索（必须在 /{name} 路由之前定义，否则 search 会被当 name 匹配）。"""
    if not q.strip():
        _skill_index._ensure_built()
        seen = set()
        results = []
        for entry in _skill_index._index:
            name = entry["skill_name"]
            if name in seen:
                continue
            seen.add(name)
            if enabled_only and not entry.get("enabled"):
                continue
            results.append({
                "skill_name": entry["skill_name"],
                "source": entry["source"],
                "description": entry["description"],
                "tags": entry["tags"],
                "enabled": entry["enabled"],
            })
        return {"query": "", "results": results[:limit]}

    results = _skill_index.search(q.strip(), limit=limit, enabled_only=enabled_only)
    return {"query": q, "results": results}


@router.get("/search/sections")
def search_skill_sections(q: str = "", limit: int = 5):
    """跨 skill 搜索 section 内容（按需加载用）。"""
    if not q.strip():
        return {"query": "", "results": []}
    results = _skill_index.search_sections(q.strip(), limit=limit)
    return {"query": q, "results": results}


@router.get("/{name}")
def get_skill(name: str):
    """获取单个 skill。"""
    return _load_skill(name)


@router.post("")
def create_skill(skill: SkillBase):
    """创建新 skill。"""
    path = _skill_path(skill.name)
    if path.exists():
        raise HTTPException(409, f"Skill 已存在: {skill.name}")
    data = skill.model_dump()
    _save_skill(data)
    rebuild_skill_index()
    return {"created": True, "skill": data}


@router.put("/{name}")
def update_skill(name: str, updates: SkillUpdate):
    """更新 skill（支持重命名：传 name 字段则改文件名并同步蒸馏 DB）。"""
    existing = _load_skill(name)
    update_data = updates.model_dump(exclude_unset=True)
    new_name = update_data.pop("name", None)
    renamed = False
    if new_name is not None:
        new_name = new_name.strip()
        if new_name and new_name != name:
            new_path = _skill_path(new_name)  # 校验 + 构造路径
            if new_path.exists():
                raise HTTPException(409, f"Skill 已存在: {new_name}")
            existing["name"] = new_name
            update_data["name"] = new_name
            renamed = True
    existing.update(update_data)
    _save_skill(existing)  # 按新名写文件
    if renamed:
        old_path = _skill_path(name)
        if old_path.exists():
            try:
                old_path.unlink()
            except OSError as e:
                logger.warning("删除旧 skill 文件失败: %s", e)
        _sync_db_skill_name(name, new_name)
    rebuild_skill_index()
    return {"updated": True, "skill": existing}


def _sync_db_skill_name(old_name: str, new_name: str) -> None:
    """蒸馏 DB 中同名 skill 记录同步改名（失败仅记日志，不阻塞）。"""
    try:
        from novel_agent.distillation.store import get_store
        store = get_store()
        for s in store.list_skills():
            if s.get("name") == old_name:
                store.update_skill(s["id"], name=new_name)
    except Exception as e:
        logger.warning("同步蒸馏 DB 改名失败: %s", e)


@router.delete("/{name}")
def delete_skill(name: str):
    """删除 skill（内置 Skill 不可删除）。"""
    path = _skill_path(name)
    if not path.exists():
        raise HTTPException(404, f"Skill 不存在: {name}")
    # 检查是否为内置 Skill
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("is_builtin"):
            raise HTTPException(403, f"内置 Skill「{name}」不可删除，可禁用")
    except (json.JSONDecodeError, OSError):
        pass
    try:
        path.unlink()
    except OSError as e:
        raise HTTPException(500, f"删除 skill 失败: {e}")
    rebuild_skill_index()
    return {"deleted": True, "name": name}


# ---- Book-to-Skill：拆书生成技能 ----


@router.post("/import-book")
async def import_book_to_skill(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    max_chapters: int = Form(50),
):
    """上传一本书（PDF/EPUB/DOCX/TXT），自动拆分章节并 LLM 逐章提炼生成 skill。

    返回 SSE 流：每个章节提炼完成后推送进度，最终推送生成的 skill JSON。

    参考 book-to-skill 开源项目（virgiliojr94/book-to-skill）：
    - 只存储提炼后的摘要，不存储原文（版权安全）
    - 核心索引 ~4K token，章节按需加载
    """
    from novel_agent.utils.file_extract import extract_text_or_image
    from novel_agent.skills.book_to_skill import book_to_skill, _slugify
    from novel_agent.config import load_config
    from novel_agent.llm.client import LLMClient

    # 1. 提取文本
    full_text, is_image = await extract_text_or_image(file)
    if is_image or not full_text.strip():
        raise HTTPException(400, "文件内容为空或为图片，无法拆书")

    book_title = title or (file.filename or "").rsplit(".", 1)[0] or "未命名"

    cfg = load_config()
    client = LLMClient(cfg.llm)

    async def _stream():
        progress_queue: asyncio.Queue = asyncio.Queue()

        async def _run():
            try:
                def on_progress(current, total, ch_title):
                    progress_queue.put_nowait({
                        "event": "progress",
                        "data": _json.dumps({
                            "current": current,
                            "total": total,
                            "title": ch_title,
                        }, ensure_ascii=False),
                    })

                skill = await book_to_skill(
                    client=client,
                    full_text=full_text,
                    book_title=book_title,
                    description=description,
                    max_chapters=max_chapters,
                    on_progress=on_progress,
                )

                # 保存 skill JSON
                skill_data = skill.to_skill_json()
                skill_data["is_builtin"] = False
                skill_data["source"] = "book-to-skill"
                path = _skill_path(skill.name)
                with open(path, "w", encoding="utf-8") as f:
                    _json.dump(skill_data, f, ensure_ascii=False, indent=2)
                # 新 skill 落盘后重建索引（含向量层），保证拆书产物立即可搜
                rebuild_skill_index()

                progress_queue.put_nowait({
                    "event": "done",
                    "data": _json.dumps({
                        "name": skill.name,
                        "description": skill.description,
                        "sections_count": len(skill.sections),
                        "path": str(path),
                    }, ensure_ascii=False),
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                progress_queue.put_nowait({
                    "event": "error",
                    "data": _json.dumps({"error": str(e)}, ensure_ascii=False),
                })

        task = asyncio.create_task(_run())

        while True:
            try:
                msg = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield msg
                if msg["event"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                if task.done():
                    break
                yield {"event": "heartbeat", "data": ""}

        await task

    return EventSourceResponse(_stream())


def load_skill_section_by_keywords(query: str, skill_name: str, limit: int = 3) -> list[dict]:
    """按关键词从指定 skill 中加载最相关的章节段落（按需加载）。

    用于生成时只注入相关章节而非全量，降低 token 消耗。
    """
    path = _skill_path(skill_name)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            skill = _json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    sections = skill.get("sections", [])
    if not sections:
        return []

    query_lower = query.lower()
    query_terms = [t.strip() for t in query_lower.split() if t.strip()]

    scored: list[tuple[float, dict]] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        content = (sec.get("content") or "").lower()
        keywords = [k.lower() for k in (sec.get("keywords") or [])]
        name = (sec.get("name") or "").lower()

        score = 0.0
        for term in query_terms:
            if term in name:
                score += 3.0
            for kw in keywords:
                if term in kw or kw in term:
                    score += 2.0
            if term in content:
                score += 1.0

        if score > 0:
            scored.append((score, sec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored[:limit]]


# ---- Prompt 注入（供两条生成路径共用）----


def load_enabled_skills_for_injection(exclude_sources: tuple[str, ...] = ()) -> str:
    """加载所有启用的 Skills，拼接成 prompt section 供注入。

    供两条生成路径共用，确保 Skills 注入逻辑一致、不分叉：
    - 正式写作页：novel_agent.orchestrator.nodes._build_bible_injections
    - 交互式创作：novel_agent.api.routes_generation.interactive_chat_stream

    借鉴 DeterminFlow 的 auto_inject 模式：只注入 enabled=True 的 skill，
    每个 skill 的 sections 内容拼接成一段，内置 skill 与用户自建统一处理。
    Skills 中定义的能力约束（如写作风格、行为规范）会在创作时被 LLM 遵循。

    Args:
        exclude_sources: 需要排除的 skill source（如 "corpus" 语料型 skill 内容庞大，
            只支持按上下文检索注入，不能全量注入）
    """
    try:
        _seed_default_skills_if_empty()
        d = _skills_dir()
        skills: list[dict] = []
        for p in sorted(d.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    skills.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
    except Exception:
        return ""

    enabled_skills = [
        s for s in skills
        if s.get("enabled", True)
        and s.get("auto_inject", True)  # 默认自动注入；关掉 auto_inject 则不参与注入
        and s.get("source") not in exclude_sources
    ]
    if not enabled_skills:
        return ""

    parts: list[str] = []
    for skill in enabled_skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        header = f"【Skill·{name}】" if name else "【Skill】"
        if desc:
            header += f"（{desc}）"

        # book-to-skill 技能：只注入概览索引，不注入全量章节（按需加载）
        if skill.get("source") == "book-to-skill":
            overview = (skill.get("overview") or "").strip()
            glossary = (skill.get("glossary") or "").strip()
            cheatsheet = (skill.get("cheatsheet") or "").strip()
            body = overview
            if glossary:
                body += "\n\n" + glossary
            if cheatsheet:
                body += "\n\n" + cheatsheet
            if body:
                parts.append(header + "\n" + body)
            continue

        # 普通 skill：注入全部 sections
        sections = skill.get("sections", []) or []
        body_parts: list[str] = []
        for sec in sections:
            if isinstance(sec, dict):
                content = (sec.get("content") or "").strip()
            elif isinstance(sec, str):
                content = sec.strip()
            else:
                content = ""
            if content:
                body_parts.append(content)
        if not body_parts:
            continue
        parts.append(header + "\n" + "\n\n".join(body_parts))

    if not parts:
        return ""
    return (
        "【Skills 能力注入--创作时遵循以下能力约束】\n\n"
        + "\n\n---\n\n".join(parts)
    )


# ---- 跨 Skill 统一索引 ----


class _SkillIndex:
    """跨 skill 统一索引：内存倒排索引（关键词加权）+ 向量语义检索增强。

    索引所有 skill 来源（内置 / 用户自建 / book-to-skill / 蒸馏），
    提供关键词搜索和按需加载能力。向量层为增强：embedding 可用时把条目
    写入 chroma collection，搜索时关键词结果优先、向量召回补漏语义相近
    但字词不匹配的条目；embedding 不可用/异常时透明降级为纯关键词。
    """

    def __init__(self):
        self._index: list[dict] = []  # 扁平化索引条目
        self._built = False
        self._lock = threading.Lock()
        # 向量增强层（惰性初始化）
        self._client = None
        self._collection = None
        self._embedding_function = None
        self._vector_enabled = False
        self._vector_init_tried = False
        # 向量查询 LRU 缓存（避免每次请求重复 embedding 网络调用）
        self._query_cache: dict[tuple, list[dict]] = {}
        self._cache_order: list[tuple] = []

    def _ensure_built(self):
        if not self._built:
            self.rebuild()

    def rebuild(self):
        """重建索引：扫描 skills 目录 + 蒸馏 DB + 同步向量层。"""
        with self._lock:
            self._rebuild_locked()
        # 锁外同步向量层并清空查询缓存（向量同步较慢，不占索引锁）
        self._query_cache.clear()
        self._cache_order.clear()
        self._sync_vector()

    def remove_skill(self, skill_name: str) -> None:
        """增量移除某 skill 的全部索引条目（删除单个 skill 用）。

        只从内存索引过滤 + 向量层按 skill_name 删除，不触发全量重建——
        避免删除一个 skill 时把上千条目重新 embedding（几百次网络请求，很慢）。
        """
        if not skill_name:
            return
        with self._lock:
            before = len(self._index)
            self._index = [e for e in self._index if e.get("skill_name") != skill_name]
            removed = before - len(self._index)
        try:
            self._ensure_vector()
            if self._collection is not None and removed:
                self._collection.delete(where={"skill_name": skill_name})
        except Exception as e:
            logger.warning("skill 索引增量移除向量条目失败（下次 rebuild 兜底）: %s", e)
        self._query_cache.clear()
        self._cache_order.clear()

    def _rebuild_locked(self):
        """重建索引主体（持锁执行）：扫描 skills 目录 + 蒸馏 DB。"""
        entries: list[dict] = []

        # 1. 文件 skills（内置/用户自建/book-to-skill/蒸馏写入的）
        try:
            _seed_default_skills_if_empty()
            d = _skills_dir()
            for p in sorted(d.glob("*.json")):
                try:
                    with open(p, encoding="utf-8") as f:
                        skill = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                name = skill.get("name", p.stem)
                desc = skill.get("description", "")
                source = skill.get("source", "")
                distilled = skill.get("distilled", False)
                tags = skill.get("tags", [])
                enabled = skill.get("enabled", True)

                # 索引 skill 级别
                entries.append({
                    "skill_name": name,
                    "source": source or ("distillation" if distilled else "builtin"),
                    "description": desc,
                    "tags": tags,
                    "enabled": enabled,
                    "section_name": "",
                    "section_content_preview": desc[:200],
                    "keywords": tags,
                    "_skill": skill,
                    "_section": None,
                })

                # 索引 section 级别
                for sec in (skill.get("sections") or []):
                    if not isinstance(sec, dict):
                        continue
                    sec_name = sec.get("name", "")
                    content = sec.get("content", "")
                    kws = sec.get("keywords", [])
                    entries.append({
                        "skill_name": name,
                        "source": source or ("distillation" if distilled else "builtin"),
                        "description": desc,
                        "tags": tags,
                        "enabled": enabled,
                        "section_name": sec_name,
                        "section_content_preview": content[:200],
                        "keywords": kws,
                        "_skill": skill,
                        "_section": sec,
                    })
        except Exception:
            pass

        # 2. 蒸馏 DB skills（仅索引 DB 中的，文件中已有的跳过）
        try:
            from novel_agent.distillation.store import get_store
            store = get_store()
            db_skills = store.list_skills()
            existing_names = {e["skill_name"] for e in entries}
            for s in db_skills:
                if s["name"] in existing_names:
                    continue
                entries.append({
                    "skill_name": s["name"],
                    "source": "distillation",
                    "description": s.get("description", ""),
                    "tags": s.get("tags", []),
                    "enabled": s.get("status") == "active",
                    "section_name": "",
                    "section_content_preview": (s.get("content") or "")[:200],
                    "keywords": s.get("tags", []),
                    "_skill": None,
                    "_section": None,
                    "_db_skill": s,
                })
        except Exception:
            pass

        self._index = entries
        self._built = True

    def search(self, query: str, limit: int = 20, enabled_only: bool = False) -> list[dict]:
        """跨 skill 关键词搜索 + 向量语义补漏。

        评分：skill_name 匹配 +5, section_name 匹配 +3, keywords 匹配 +2, content 匹配 +1
        向量召回仅补充关键词未命中的语义相关条目（关键词命中结果排前）。
        """
        self._ensure_built()
        query_lower = query.lower()
        terms = [t.strip() for t in query_lower.split() if t.strip()]
        if not terms:
            return []

        scored = self._keyword_score(terms, enabled_only)
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [s[1] for s in scored[:limit]]

        # 向量语义补漏（embedding 不可用时 _vector_query 返回空，等效纯关键词）
        results = self._fuse_vector(results, query, limit, enabled_only)
        return results

    def _keyword_score(self, terms: list[str], enabled_only: bool) -> list[tuple[float, dict]]:
        """关键词加权打分（遍历内存索引条目）。"""
        scored: list[tuple[float, dict]] = []
        for entry in self._index:
            if enabled_only and not entry.get("enabled"):
                continue

            score = 0.0
            skill_name = entry.get("skill_name", "").lower()
            sec_name = entry.get("section_name", "").lower()
            keywords = [k.lower() for k in entry.get("keywords", [])]
            content = entry.get("section_content_preview", "").lower()
            desc = entry.get("description", "").lower()

            for term in terms:
                if term in skill_name:
                    score += 5.0
                if sec_name and term in sec_name:
                    score += 3.0
                if term in desc:
                    score += 2.0
                for kw in keywords:
                    if term in kw or kw in term:
                        score += 2.0
                if term in content:
                    score += 1.0

            if score > 0:
                result = {
                    "skill_name": entry["skill_name"],
                    "source": entry["source"],
                    "description": entry["description"],
                    "tags": entry["tags"],
                    "enabled": entry["enabled"],
                    "section_name": entry["section_name"],
                    "score": score,
                }
                scored.append((score, result))
        return scored

    def _fuse_vector(self, kw_results: list[dict], query: str, limit: int,
                     enabled_only: bool) -> list[dict]:
        """把向量召回结果补到关键词结果之后（去重，保持关键词优先）。"""
        vec_hits = self._vector_query(query, limit=limit * 2)
        if not vec_hits:
            return kw_results
        results = list(kw_results)
        seen = {(r["skill_name"], r.get("section_name", "")) for r in results}
        for vh in vec_hits:
            if len(results) >= limit:
                break
            key = (vh["skill_name"], vh.get("section_name", ""))
            if key in seen:
                continue
            if enabled_only and not vh.get("enabled"):
                continue
            results.append(vh)
            seen.add(key)
        return results

    def _vector_query(self, query: str, limit: int = 20) -> list[dict]:
        """向量语义检索索引条目（带 LRU 缓存，避免每次请求重复 embedding 网络调用）。

        返回与 search() 输出同构的条目列表（按语义相关度降序，score=1/(rank+1)）。
        embedding 未启用或查询异常时返回 []，调用方自然退化为关键词结果。
        """
        cache_key = (query, limit)
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]
        try:
            self._ensure_vector()
            if not self._vector_enabled or self._collection is None:
                return []
            res = self._collection.query(query_texts=[query], n_results=limit)
            metas = (res.get("metadatas") or [[]])[0] if res.get("metadatas") else []
            hits: list[dict] = []
            for rank, meta in enumerate(metas):
                if not meta:
                    continue
                hits.append({
                    "skill_name": meta.get("skill_name", ""),
                    "source": meta.get("source", ""),
                    "description": meta.get("description", ""),
                    "tags": json.loads(meta.get("tags", "[]")),
                    "enabled": bool(meta.get("enabled", True)),
                    "section_name": meta.get("section_name", ""),
                    "score": 1.0 / (rank + 1),
                    "entry_idx": meta.get("entry_idx", -1),
                })
            if hits:
                self._query_cache[cache_key] = hits
                self._cache_order.append(cache_key)
                if len(self._cache_order) > 64:
                    old = self._cache_order.pop(0)
                    self._query_cache.pop(old, None)
            return hits
        except Exception as e:
            logger.warning("skill 索引向量查询异常，降级为关键词结果: %s", e)
            return []

    def _ensure_vector(self):
        """惰性初始化向量检索层（chroma collection）。

        embedding 不可用（未配置方舟 key 且本地模型无法加载）或初始化异常时，
        向量功能保持关闭，搜索透明降级为关键词检索。
        """
        if self._vector_init_tried:
            return
        self._vector_init_tried = True
        try:
            from novel_agent.memory.archival import _build_embedding_function
            ef = _build_embedding_function(load_config())
            if ef is None:
                logger.info("skill 索引：无可用 embedding（未配置向量模型），保持关键词检索")
                return
            import chromadb
            cfg = load_config()
            chroma_dir = cfg.chroma_dir
            chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(chroma_dir))
            self._collection = self._client.get_or_create_collection(
                name="skill_entries",
                metadata={"hnsw:space": "cosine"},
                embedding_function=ef,
            )
            self._embedding_function = ef
            self._vector_enabled = True
            logger.info("skill 索引：向量语义检索已启用（chroma: skill_entries）")
        except Exception as e:
            self._vector_enabled = False
            logger.warning("skill 索引向量检索初始化失败，降级为关键词检索: %s", e)

    def _sync_vector(self):
        """把内存索引条目全量同步到 chroma collection（重建时调用）。

        embedding 分批 upsert：方舟 doubao-embedding 等 API 单次请求有 input 上限
        （实测 max 10），一次全量提交会超限。同步失败时关闭向量层并记日志，
        下次 rebuild 会再次尝试（不依赖 _vector_enabled 预判断，避免失败后永不重试）。
        """
        try:
            self._ensure_vector()
            if self._collection is None or self._client is None or self._embedding_function is None:
                return
            # 全量重建：删旧 collection 再建，避免残留已删除 skill 的条目
            self._client.delete_collection("skill_entries")
            self._collection = self._client.get_or_create_collection(
                name="skill_entries",
                metadata={"hnsw:space": "cosine"},
                embedding_function=self._embedding_function,
            )
            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict] = []
            for i, entry in enumerate(self._index):
                ids.append(f"skill_{i}")
                sec_name = entry.get("section_name", "")
                name = entry.get("skill_name", "")
                desc = entry.get("description", "")
                content = entry.get("section_content_preview", "")
                text = f"{name} - {sec_name}\n{content}" if sec_name else f"{name}\n{desc}"
                documents.append(text)
                metadatas.append({
                    "entry_idx": i,
                    "skill_name": name,
                    "source": entry.get("source", ""),
                    "description": desc,
                    "tags": json.dumps(entry.get("tags", []), ensure_ascii=False),
                    "enabled": entry.get("enabled", True),
                    "section_name": sec_name,
                })
            if ids:
                BATCH = 10  # 方舟 embedding 单次请求 input 上限
                for start in range(0, len(ids), BATCH):
                    end = start + BATCH
                    self._collection.upsert(
                        ids=ids[start:end],
                        documents=documents[start:end],
                        metadatas=metadatas[start:end],
                    )
            self._vector_enabled = True
            logger.info("skill 索引：向量层已同步 %d 条条目", len(ids))
        except Exception as e:
            logger.warning("skill 索引向量层同步失败，保持关键词检索: %s", e)
            self._vector_enabled = False

    def search_sections(self, query: str, limit: int = 5) -> list[dict]:
        """跨 skill 搜索 section 内容（用于按需加载注入）。

        返回 [{skill_name, section_name, content, score}]；向量召回补漏语义相近 section。
        """
        self._ensure_built()
        query_lower = query.lower()
        terms = [t.strip() for t in query_lower.split() if t.strip()]
        if not terms:
            return []

        scored: list[tuple[float, dict]] = []
        for entry in self._index:
            sec = entry.get("_section")
            if not sec or not isinstance(sec, dict):
                continue
            content = (sec.get("content") or "").lower()
            sec_name = (sec.get("name") or "").lower()
            kws = [k.lower() for k in (sec.get("keywords") or [])]

            score = 0.0
            for term in terms:
                if term in sec_name:
                    score += 3.0
                for kw in kws:
                    if term in kw or kw in term:
                        score += 2.0
                if term in content:
                    score += 1.0

            if score > 0:
                scored.append((score, {
                    "skill_name": entry["skill_name"],
                    "section_name": sec.get("name", ""),
                    "content": sec.get("content", ""),
                    "score": score,
                }))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [s[1] for s in scored[:limit]]

        # 向量语义补漏（section 级；embedding 不可用时 _vector_query 返回空）
        vec_hits = self._vector_query(query, limit=limit * 2)
        seen = {(r["skill_name"], r["section_name"]) for r in results}
        for vh in vec_hits:
            if len(results) >= limit:
                break
            if not vh.get("section_name"):
                continue
            key = (vh["skill_name"], vh["section_name"])
            if key in seen:
                continue
            content = ""
            ei = vh.get("entry_idx", -1)
            if 0 <= ei < len(self._index):
                sec = self._index[ei].get("_section")
                if isinstance(sec, dict):
                    content = sec.get("content", "")
            if not content:
                continue
            results.append({
                "skill_name": vh["skill_name"],
                "section_name": vh["section_name"],
                "content": content,
                "score": vh.get("score", 0),
            })
            seen.add(key)
        return results


# 全局单例
_skill_index = _SkillIndex()


def rebuild_skill_index():
    """重建 skill 索引（skill 增删改后调用）。"""
    _skill_index.rebuild()


def remove_skill_from_index(skill_name: str):
    """增量移除某 skill 的索引条目（删除单个 skill 时调用，避免全量重建）。"""
    _skill_index.remove_skill(skill_name)


def load_enabled_skills_for_injection_with_context(context: str = "") -> str:
    """带上下文的 skill 注入：普通 skill 全量注入，book-to-skill 按上下文按需加载。

    当 context 非空时，book-to-skill 技能只注入与上下文相关的 section（跨 skill 索引检索），
    而非只注入概览。这样在写"战斗场景"时能自动加载战斗相关技法，写"对话"时加载对话技法。

    Args:
        context: 当前章节的上下文信息（章节标题+摘要+大纲），用于按需检索
    """
    if not context.strip():
        # 无上下文时走原有逻辑（语料型 skill 内容庞大，无上下文无法检索，不注入）
        return load_enabled_skills_for_injection(exclude_sources=("corpus",))

    try:
        _seed_default_skills_if_empty()
        d = _skills_dir()
        skills: list[dict] = []
        for p in sorted(d.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    skills.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue
    except Exception:
        return ""

    enabled_skills = [
        s for s in skills
        if s.get("enabled", True) and s.get("auto_inject", True)
    ]
    if not enabled_skills:
        return ""

    # 确保索引已构建
    _skill_index._ensure_built()

    parts: list[str] = []
    for skill in enabled_skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        header = f"【Skill·{name}】" if name else "【Skill】"
        if desc:
            header += f"（{desc}）"

        # book-to-skill / 语料型（source=corpus）技能：按上下文按需加载相关 section，
        # 只注入命中的条目而非整库，避免 token 膨胀
        if skill.get("source") in ("book-to-skill", "corpus"):
            body = ""
            if skill.get("source") == "book-to-skill":
                overview = (skill.get("overview") or "").strip()
                glossary = (skill.get("glossary") or "").strip()
                cheatsheet = (skill.get("cheatsheet") or "").strip()
                body = overview
                if glossary:
                    body += "\n\n" + glossary
                if cheatsheet:
                    body += "\n\n" + cheatsheet

            # 按上下文检索相关 section（跨 skill 索引）；先取足量再按 skill 过滤，
            # 保证多个语料 skill 都能均衡命中（每个最多 6 条）
            relevant = _skill_index.search_sections(context, limit=30)
            relevant_for_this = [r for r in relevant if r["skill_name"] == name][:6]
            if relevant_for_this:
                label = "本章节相关技法" if skill.get("source") == "book-to-skill" else "本章节相关语料"
                body += f"\n\n【{label}】"
                for r in relevant_for_this:
                    body += f"\n\n### {r['section_name']}\n{r['content'][:2000]}"

            if body:
                parts.append(header + "\n" + body)
            continue

        # 蒸馏 skill：全量注入（风格约束需要完整遵守）
        # 普通 skill：全量注入
        sections = skill.get("sections", []) or []
        body_parts: list[str] = []
        for sec in sections:
            if isinstance(sec, dict):
                content = (sec.get("content") or "").strip()
            elif isinstance(sec, str):
                content = sec.strip()
            else:
                content = ""
            if content:
                body_parts.append(content)
        if not body_parts:
            continue
        parts.append(header + "\n" + "\n\n".join(body_parts))

    if not parts:
        return ""
    return (
        "【Skills 能力注入--创作时遵循以下能力约束】\n\n"
        + "\n\n---\n\n".join(parts)
    )
