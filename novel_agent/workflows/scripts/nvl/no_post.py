#!/usr/bin/env python3
"""NO 后处理：读 no_output.json，根据 is_new_volume 覆盖或追加 near_term_outline.md。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/script-library/nvl/no_post/no_post.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）

用法:
  python no_post.py --input cache/no/no_output.json [--volume-number 2]
  --volume-number 传入时，若 is_new_volume=true 则覆盖写入该卷近纲。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path


def _safe_rel(raw_path: str) -> str:
    """路径安全校验：只允许工作区内相对路径，拒绝绝对路径与 .. 穿越。"""
    p = Path(raw_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    return raw_path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean(text):
    return text.replace("——", "，")


def render_chapter(ch):
    lines = [
        f"### 第{ch.get('number', '?')}章 · {ch.get('title', '')}",
        f"- **情节摘要**：{ch.get('summary', '—')}",
        f"- **节奏**：{ch.get('rhythm', '—')}",
        f"- **世界时间推进**：{ch.get('time_advance', '?')}",
    ]
    return "\n".join(lines)


def render_full(data):
    """首次跑该卷/重写该卷：输出完整近纲。"""
    cr = data.get("chapter_range", {})
    start = cr.get("start", "?")
    end = cr.get("end", "?")
    arc = data.get("arc_name", "")

    lines = [f"# 近期大纲（第{start}-{end}章）"]
    if arc:
        lines.extend(["", f"## 当前弧线 · {arc}"])

    for ch in data.get("chapters", []):
        lines.extend(["", render_chapter(ch)])

    char_arcs = data.get("character_arcs", [])
    if char_arcs:
        lines.extend(["", "## 角色弧线"])
        for ca in char_arcs:
            lines.append(f"- **{ca.get('name', '?')}**：{ca.get('from', '?')} → {ca.get('to', '?')} → {ca.get('change', '?')}")

    dp = data.get("decision_points", [])
    if dp:
        lines.extend(["", "## 关键决策点"])
        for d in dp:
            lines.append(f"- 第{d.get('chapter', '?')}章：{d.get('character', '?')}面临{d.get('choice', '?')}，将影响{d.get('impact', '?')}")

    return clean("\n".join(lines)) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NO 输出渲染")
    parser.add_argument("--input", required=True, help="no_output.json 路径")
    parser.add_argument("--volume-number", type=int, default=None, help="目标卷号（用于日志，不影响行为——行为由 agent 的 is_new_volume 控制）")
    args = parser.parse_args(argv)

    _safe_rel(args.input)

    data = load_json(args.input)
    chapters = data.get("chapters", [])

    if not chapters:
        print("[OK] 无新增章，跳过")
        return

    outpath = "outline/near_term_outline.md"
    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)

    if data.get("is_new_volume", False):
        # 新卷或重写：覆盖写入
        md = render_full(data)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(md)
        action = "覆盖"
    else:
        # 追加新章到末尾
        chunks = []
        for ch in chapters:
            chunks.append(render_chapter(ch))
        md = clean("\n\n".join(chunks)) + "\n"

        existing = ""
        if os.path.exists(outpath):
            with open(outpath, "r", encoding="utf-8") as f:
                existing = f.read()
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(existing + "\n" + md)
        action = "追加"

    # JSON 缓存
    os.makedirs("cache/no", exist_ok=True)
    with open("cache/no/near_term.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    vn = data.get("volume_number", "?")
    size = len(md.encode("utf-8"))
    print(f"[OK] 卷{vn} {action} {len(chapters)} 章 → {outpath} (+{size}B)")


def run(args: list[str] | None = None, workspace: Path | None = None) -> dict:
    """工作流引擎进程内调用入口。返回 {"status": "ok"/"failed", ...}"""
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
    except SystemExit as exc:  # argparse 或显式 sys.exit
        exit_code = exc.code if isinstance(exc.code, int) else 1
        if exc.code and not isinstance(exc.code, int):
            error = str(exc.code)
    except Exception as exc:  # 确定性脚本需把异常转为失败状态
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
