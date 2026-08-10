#!/usr/bin/env python3
"""从 skeleton JSON 中提取角色名列表，产出 list 变量供循环网关使用。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/workflows/character/script/extract_names.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）

用法:
    python extract_names.py --file cache/character/skeleton.json

产出:
    <WF_VAR>character_names:["张三","李四","王五"]</WF_VAR>
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path


def _safe_rel(raw_path: str) -> str:
    """路径安全校验：只允许工作区内相对路径，拒绝绝对路径与 .. 穿越。"""
    p = Path(raw_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    return raw_path


def _extract_json(raw: str) -> str:
    text = raw.strip()
    if not text:
        return text
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, count=1)
    text = re.sub(r'\n?```\s*$', '', text, count=1)
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('‘', "'").replace('’', "'")
    text = text.replace('«', '"').replace('»', '"')
    text = text.replace('„', '"').replace('‚', "'")
    text = text.replace('＂', '"')
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text.strip()


def _drop_obvious_orphan_lines(text: str) -> str:
    """丢弃明显不是 JSON token 的行。

    LLM 输出偶尔会在对象内部残留一个悬挂片段，例如：
        寻者",
    与其让整条角色管线失败，不如丢弃该行、保留其余合法结构。
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if stripped[0] in '{[}]':
            kept.append(line)
            continue
        if stripped.startswith('"') and ':' in stripped:
            kept.append(line)
            continue
        if stripped.startswith('"') and stripped.rstrip(',').endswith('"'):
            kept.append(line)
            continue
        # 其余行大概率是孤立的自然语言片段
    return "\n".join(kept)


def _load_json_tolerant(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    text = _extract_json(raw)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        repaired = _drop_obvious_orphan_lines(text)
        repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
        data = json.loads(repaired, strict=False)
        # 把修复后的 JSON 落盘，让下游节点也能读到合法 JSON
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("[extract_names] 已修复 skeleton JSON 中的孤立文本行", file=sys.stderr)
        return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="skeleton JSON 文件路径")
    args = parser.parse_args(argv)

    _safe_rel(args.file)

    try:
        data = _load_json_tolerant(args.file)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    names = [c["name"] for c in data.get("characters", []) if c.get("name")]

    if not names:
        print("[extract_names] 错误：未找到角色名", file=sys.stderr)
        sys.exit(1)

    # 安全截断：最多 8 个角色，防止后续循环管线耗时过长/内存不足
    MAX_CHARACTERS = 8
    if len(names) > MAX_CHARACTERS:
        print(f"[extract_names] 警告：角色数 {len(names)} 超过上限 {MAX_CHARACTERS}，截断为前 {MAX_CHARACTERS} 个", file=sys.stderr)
        names = names[:MAX_CHARACTERS]

    # 输出 list 变量（双引号 JSON 数组）
    names_json = json.dumps(names, ensure_ascii=False)
    print(f"<WF_VAR>character_names:{names_json}</WF_VAR>")
    print(f"<script_out>已提取 {len(names)} 个角色: {', '.join(names)}</script_out>")


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
