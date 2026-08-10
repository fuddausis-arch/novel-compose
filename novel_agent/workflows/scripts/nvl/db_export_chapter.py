#!/usr/bin/env python3
"""把数据库/项目中的章节资产导出到工作流文件区（DB → 文件方向）。

润色管线（polish）等 bishu-novel 工作流按 `story/{章节号}/chapter.md`
读取正文，但用户正常写的章节（写作页/交互式创作单 Agent）存的是
项目 `chapters/第NNN章_*.md` 文件，不会自动落进 `story/`。
本脚本在润色管线开头跑一次，把真实正文 + 审校输入导出到工作区，
解决「找不到正文」，并让声线/情感审校拿到 DB 里的角色声线与单章指导。

导出内容（相对工作区）：
- story/{chapter}/chapter.md         章节正文（修复找不到正文）
- meta/character_voice.md            角色声线锚（VC 用）
- outline/guide.md                   单章指导/信息边界（PC 与 arbiter knowledge-delta 用）

依赖：仅项目文件系统 + SQLite（bible.db），与 bridge.py 同一数据源。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

# ============================================================
# 路径/项目辅助（与 bridge.py 一致的约定）
# ============================================================

_DB_PATH = None


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        from novel_agent.config import load_config
        cfg = load_config()
        _DB_PATH = cfg.project_data_dir / "bible.db"
    return _DB_PATH


def _project_id_from_workspace(workspace: Path) -> int | None:
    ws = workspace.resolve()
    for parent in ws.parents:
        if parent.name == "projects" and ws.name.isdigit():
            return int(ws.name)
        if parent.parent.name == "projects" and parent.name.isdigit():
            return int(parent.name)
    return None


def _connect(project_id: int) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _chapter_file_for(workspace: Path, chapter: int) -> Path | None:
    """在工作区 chapters/ 下找第 NNN 章的正文文件。"""
    pattern = f"第{chapter:03d}章_*.md"
    if not (workspace / "chapters").is_dir():
        return None
    matches = list((workspace / "chapters").glob(pattern))
    # 章节号可能超 3 位（0001..），再宽松匹配一次
    if not matches:
        matches = [p for p in (workspace / "chapters").glob("第*章_*.md")
                   if re.match(rf"第{chapter}章_", p.name)]
    return matches[0] if matches else None


def _export_chapter_body(workspace: Path, chapter: int) -> str:
    src = _chapter_file_for(workspace, chapter)
    if src is None:
        return ""
    raw = src.read_text(encoding="utf-8")
    # 去掉文件头部的 `# 第N章 标题` 标题行，只留正文
    lines = raw.split("\n")
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    _write_text(workspace / "story" / f"{chapter:04d}" / "chapter.md", body)
    return body


def _export_voice_anchors(project_id: int, workspace: Path) -> None:
    """从 characters 表导出角色声线锚（name/role/language_style/personality）。"""
    try:
        conn = _connect(project_id)
        rows = conn.execute(
            "SELECT name, role, language_style, personality FROM characters "
            "WHERE project_id=? ORDER BY id",
            (project_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return
    if not rows:
        return
    lines = ["# 角色声线锚", ""]
    for r in rows:
        name = r["name"] or "未知"
        role = r["role"] or ""
        lines.append(f"## {name}（{role}）")
        if r["language_style"]:
            lines.append(f"- 语言风格/经典台词：{r['language_style']}")
        if r["personality"]:
            lines.append(f"- 性格：{r['personality']}")
        lines.append("")
    _write_text(workspace / "meta" / "character_voice.md", "\n".join(lines))


def _export_guide(project_id: int, chapter: int, workspace: Path) -> None:
    """从 outlines 表导出当前章的单章指导（标题/摘要/约束/角色边界）。"""
    try:
        conn = _connect(project_id)
        row = conn.execute(
            "SELECT title, summary, required_beats, owed_debts, required_hooks, "
            "character_constraints FROM outlines "
            "WHERE project_id=? AND level='chapter' AND (order=? OR summary LIKE ?) "
            "ORDER BY CASE WHEN order=? THEN 0 ELSE 1 END LIMIT 1",
            (project_id, chapter, f"%第{chapter}章%", chapter),
        ).fetchone()
        conn.close()
    except Exception:
        row = None
    if row is None:
        return

    def _fmt_list(raw: str) -> str:
        if not raw:
            return "（无）"
        try:
            data = json.loads(raw)
        except Exception:
            return raw
        if isinstance(data, list):
            return "; ".join(
                f"{x.get('type','')}({x.get('tier','')}/{x.get('intensity','')})"
                if isinstance(x, dict) else str(x)
                for x in data
            )
        if isinstance(data, dict):
            return "; ".join(f"{k}:{v}" for k, v in data.items())
        return str(data)

    lines = [f"# 单章指导（第{chapter}章）", ""]
    if row["title"]:
        lines.append(f"- 标题：{row['title']}")
    if row["summary"]:
        lines.append(f"- 摘要：{row['summary']}")
    lines.append(f"- 必达节拍：{_fmt_list(row['required_beats'])}")
    lines.append(f"- 应还欠账：{_fmt_list(row['owed_debts'])}")
    lines.append(f"- 必留钩子：{_fmt_list(row['required_hooks'])}")
    if row["character_constraints"]:
        # 角色约束含位置/情绪 = 信息边界的一部分，喂给 arbiter knowledge-delta
        lines.append(f"- 角色约束（含信息边界）：{_fmt_list(row['character_constraints'])}")
    _write_text(workspace / "outline" / "guide.md", "\n".join(lines))


def _export(project_id: int | None, chapter: int, workspace: Path) -> dict[str, Any]:
    pid = project_id or _project_id_from_workspace(workspace)
    if pid is None:
        return {"status": "failed", "error": "无法从工作区反推 project_id，请显式传 --project"}
    notes = []
    body = _export_chapter_body(workspace, chapter)
    if not body:
        notes.append(f"未找到第{chapter}章正文（chapters/），story/chapter.md 未生成")
    else:
        notes.append(f"已导出正文 {len(body)} 字 → story/{chapter:04d}/chapter.md")
    _export_voice_anchors(pid, workspace)
    _export_guide(pid, chapter, workspace)
    return {
        "status": "ok" if body else "warning",
        "stdout": "\n".join(notes),
        "notes": notes,
    }


# ============================================================
# CLI / run() 入口（与其它 nvl 脚本一致）
# ============================================================

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把数据库章节资产导出到工作流文件区")
    parser.add_argument("--chapter", required=True, help="章节号（如 1 或 0001）")
    parser.add_argument("--project", default="", help="project_id（省略则从工作区反推）")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    workspace = Path(os.getcwd()).resolve()
    chapter = int(str(args.chapter).strip().lstrip("0") or "0")
    project_id = int(args.project) if args.project.strip().isdigit() else None
    result = _export(project_id, chapter, workspace)
    for note in result.get("notes", []):
        print(f"  · {note}")
    # 找不到可导出的章节文件（如 mvp 路径只写 story/chapter.md、不写 chapters/）时，
    # 视为空转 no-op：story/chapter.md 已由上游产出，不必失败卡住后续节点。
    if result["status"] == "warning":
        print("  · 未找到章节文件可导出，沿用上游已产出的 story/chapter.md")
    if result["status"] == "failed":
        raise SystemExit(result.get("error", "导出失败"))


def run(args: list[str] | None = None, workspace: Path | None = None) -> dict:
    ws = Path(workspace).resolve() if workspace else Path(os.getcwd()).resolve()
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    prev_cwd = os.getcwd()
    exit_code = 0
    error = ""
    try:
        os.chdir(ws)
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            main(args)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
        if exc.code and not isinstance(exc.code, int):
            error = str(exc.code)
    except Exception as exc:
        exit_code = 1
        error = str(exc)
    finally:
        os.chdir(prev_cwd)
    result: dict = {
        "status": "ok" if exit_code == 0 else "failed",
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
    }
    if exit_code:
        result["exit_code"] = exit_code
    if error:
        result["error"] = error
    return result


if __name__ == "__main__":
    main()
