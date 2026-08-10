#!/usr/bin/env python3
"""SE 后处理：se_output.json → storyboard.md（四维度意图卡片）。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/script-library/nvl/se_post/se_post.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）
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


def render_field(value, max_len=60):
    """渲染单个字段，截断标注。"""
    s = str(value)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SE JSON → storyboard.md 渲染")
    parser.add_argument("--input", required=True, help="SE 的 JSON 输出")
    parser.add_argument("--output", required=True, help="渲染后的 MD 路径")
    args = parser.parse_args(argv)

    _safe_rel(args.input)
    _safe_rel(args.output)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    sb = data.get("storyboard", {})
    plot = sb.get("plot", {})
    char = sb.get("character", {})
    narr = sb.get("narrative", {})
    style = sb.get("style", {})

    # 从输出路径提取章节号
    chapter = os.path.basename(os.path.dirname(args.output)) or "?"

    lines = []
    lines.append(f"# 第{chapter}章 · 意图卡片")
    lines.append("")

    # ── 一、剧情导演 ──
    lines.append("## 一、剧情导演")
    lines.append("")
    lines.append(f"**本章目标**")
    lines.append(render_field(plot.get("chapter_goal", "无")))
    lines.append("")
    lines.append(f"**核心冲突**")
    lines.append(render_field(plot.get("core_conflict", "无")))
    lines.append("")
    lines.append(f"**关键推进**")
    for beat in plot.get("key_beats", []):
        lines.append(f"- {render_field(beat)}")
    lines.append("")
    lines.append(f"**悬念设计**")
    lines.append(render_field(plot.get("suspense", "无")))
    lines.append("")
    hi = plot.get("hook_intent", "无")
    if hi and hi != "无":
        lines.append(f"**伏笔意图**")
        lines.append(render_field(hi))
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 二、人物导演 ──
    lines.append("## 二、人物导演")
    lines.append("")
    rel_moves = char.get("relationship_moves", [])
    if rel_moves:
        lines.append("**关系推进**")
        for rm in rel_moves:
            pair = rm.get("pair", "?→?")
            change = rm.get("change", "")
            trigger = rm.get("trigger", "")
            lines.append(f"- {pair}：{render_field(change)}。触发感：{render_field(trigger, 30)}")
        lines.append("")
    imps = char.get("impressions", [])
    if imps:
        lines.append("**印象锚点**")
        for im in imps:
            name = im.get("name", "?")
            side = im.get("side", "")
            lines.append(f"- {name}：{render_field(side, 50)}")
        lines.append("")
    arcs = char.get("emotion_arcs", [])
    if arcs:
        lines.append("**情感走向**")
        for ea in arcs:
            name = ea.get("name", "?")
            frm = ea.get("from", "")
            mid = ea.get("mid", "")
            to = ea.get("to", "")
            trig = ea.get("trigger", "")
            lines.append(f"- {name}：从{frm}→{mid}→{to}。触发点：{render_field(trig, 30)}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 三、叙事导演 ──
    lines.append("## 三、叙事导演")
    lines.append("")
    lines.append(f"**推荐技巧**")
    lines.append(render_field(narr.get("technique", "无"), 40))
    lines.append("")
    lines.append(f"**原因**")
    lines.append(render_field(narr.get("reason", "无")))
    lines.append("")
    gaps = narr.get("info_gaps", [])
    if gaps:
        lines.append("**信息差设计**")
        for g in gaps:
            desc = g.get("description", "")
            dur = g.get("duration", "")
            lines.append(f"- {render_field(desc)}")
            lines.append(f"- 持续：{dur}")
            res = g.get("resolve_ids", [])
            if res:
                lines.append(f"- 本章兑现的信息黑洞：{', '.join(map(str, res))}")
            dfr = g.get("defer_ids", [])
            if dfr:
                lines.append(f"- 留给后续的：{', '.join(map(str, dfr))}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 四、风格导演 ──
    lines.append("## 四、风格导演")
    lines.append("")
    lines.append(f"**本章节奏**")
    lines.append(render_field(style.get("rhythm", "无"), 40))
    lines.append("")
    lines.append(f"**对白/描写侧重**")
    lines.append(render_field(style.get("dialogue_action", "无"), 30))
    lines.append("")
    lines.append(f"**氛围调性**")
    lines.append(render_field(style.get("atmosphere", "无"), 50))
    lines.append("")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] {args.input} → {args.output}")


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
