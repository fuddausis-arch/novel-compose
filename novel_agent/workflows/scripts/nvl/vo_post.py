#!/usr/bin/env python3
"""VO 后处理：读 vo_output.json，渲染 MD，新卷追加/重写替换 volume_outline.md。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/script-library/nvl/vo_post/vo_post.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）

用法:
  python vo_post.py --input cache/vo/vo_output.json [--volume-number 2]
  --volume-number 不传则默认追加新卷，传了则替换对应卷的 MD 段落。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
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


def render_volume(data):
    vn = data.get("volume_number", "?")
    title = data.get("title", "?")
    cr = data.get("chapter_range", {})
    start = cr.get("start", "?")
    end = cr.get("end", "?")

    lines = [
        f"## 卷{vn} · {title}（第{start}-{end}章）",
        "",
        f"### 本卷定位",
        data.get("positioning", "—"),
    ]

    acts = data.get("acts", {})
    if acts:
        lines.extend(["", "### 三幕功能标注"])
        for act_name, act_label in [("establish", "第一幕·建立"), ("confront", "第二幕·对抗"), ("resolve", "第三幕·收束")]:
            a = acts.get(act_name, {})
            if a:
                lines.append(f"- **{act_label}**（约{a.get('chapters', '?')}）：{a.get('content', '—')}")

    c = data.get("conflicts", {})
    lines.extend([
        "", "### 核心冲突",
        f"- **外部**：{c.get('external', '—')}",
        f"- **内部**：{c.get('internal', '—')}",
        f"- **底层**：{c.get('underlying', '—')}",
    ])

    nodes = data.get("nodes", [])
    if nodes:
        lines.extend(["", "### 本卷关键节点"])
        for n in nodes:
            lines.append(f"- 节点{n.get('id', '?')}：{n.get('description', '—')} → 代价/后果：{n.get('consequence', '—')}")

    chars = data.get("characters", [])
    if chars:
        lines.extend(["", "### 本卷出场角色"])
        for ch in chars:
            lines.append(f"- **{ch.get('name', '?')}**：{ch.get('identity', '—')}")
            lines.append(f"  - 叙事功能：{ch.get('narrative_function', '—')}")

    ending = data.get("ending", {})
    lines.extend([
        "", "### 卷末落点",
        "本卷结束时：",
        f"- 角色状态：{ending.get('character_state', '—')}",
        f"- 悬念遗留：{ending.get('suspense', '—')}",
        f"- 情绪余韵：{ending.get('emotional_aftertaste', '—')}",
    ])

    st = data.get("style_tone", "")
    if st:
        lines.extend(["", "### 风格基调", st])

    return clean("\n".join(lines)) + "\n"


def replace_volume_section(existing, vn, md):
    """在 existing 中查找 ## 卷{vn} · 段落并替换为 md。未找到则追加。"""
    pattern = re.compile(rf"(## 卷{vn} · .+?\n(?:(?!## 卷).+\n)*)", re.MULTILINE)
    match = pattern.search(existing)
    if match:
        # 找到：替换该段落
        before = existing[:match.start()]
        after = existing[match.end():]
        # 去掉尾部多余换行，保持整洁
        result = before.rstrip("\n") + "\n\n" + md.strip("\n") + "\n"
        if after.strip():
            result += "\n" + after.lstrip("\n")
        return result, "替换"
    else:
        # 未找到：追加
        if not existing.strip():
            existing = "# 卷大纲\n\n"
        return existing.rstrip("\n") + "\n\n" + md, "追加"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="VO 输出渲染追加/替换")
    parser.add_argument("--input", required=True, help="vo_output.json 路径")
    parser.add_argument("--volume-number", type=int, default=None, help="目标卷号。不传则追加，传了则替换")
    args = parser.parse_args(argv)

    _safe_rel(args.input)

    data = load_json(args.input)
    vn = data.get("volume_number", "?")
    md = render_volume(data)

    outpath = "outline/volume_outline.md"
    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)

    existing = ""
    if os.path.exists(outpath):
        with open(outpath, "r", encoding="utf-8") as f:
            existing = f.read()

    if args.volume_number is not None:
        result, action = replace_volume_section(existing, args.volume_number, md)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        # 原有行为：追加
        if not existing.strip():
            existing = "# 卷大纲\n\n"
        result = existing + "\n" + md
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(result)
        action = "追加"

    # JSON 缓存
    os.makedirs("cache/vo", exist_ok=True)
    with open("cache/vo/volume.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size = len(md.encode("utf-8"))
    print(f"[OK] 卷{vn} {action} → {outpath} (+{size}B)")


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
