"""Coding 工具集 — 10 个核心编码工具（移植自 DeterminFlow tools/coding_tools.py）。

工具清单（CODING_TOOL_NAMES 为唯一 source of truth）：
- read_file / write_to_file / replace_in_file
- search_files（内容正则搜索，ripgrep 优先，Python 降级）
- search_file（文件名 glob 搜索）
- list_files / list_code_definitions
- apply_diff（SEARCH/REPLACE 块批量编辑）
- execute_command（终端命令，含审批钩子）
- ask_user（向用户提问）

与 DeterminFlow 差异：
- 不依赖 langchain StructuredTool，统一为 `async fn(...) -> str(JSON)` 形式，
  由 chat/tools.py 的注册层包装为 OpenAI function calling schema。
- 会话上下文使用 novel_agent.chat.session_context（contextvars）。
- 沙箱开关 / 文件大小上限 / 命令超时从 config_schemas 的 coding_config 读取，
  缺省时使用安全默认值。
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# coding 工具名称集合 —— 本模块是唯一 source of truth
CODING_TOOL_NAMES: set[str] = {
    "read_file", "write_to_file", "replace_in_file",
    "search_files", "search_file", "list_files", "list_code_definitions",
    "apply_diff", "execute_command", "ask_user",
}

# 安全默认值（可通过项目 coding_config.json 覆盖）
_DEFAULTS = {
    "path_sandbox_enabled": True,
    "max_file_size": 1024 * 1024,  # 1MB
    "cmd_timeout": 120,
    "tools_enabled": True,
}

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "dist", "build",
    ".next", ".turbo", "target",
}
_MAX_DIR_ENTRIES = 500
_MAX_RIPGREP_RESULTS = 100


async def _run_io(func, *args, **kwargs):
    """在 I/O 线程池中执行同步函数，防止阻塞事件循环。"""
    return await asyncio.to_thread(func, *args, **kwargs)


def _get_coding_config(workspace_path: str) -> dict:
    """读取项目 coding_config.json，缺省返回安全默认值。"""
    cfg = dict(_DEFAULTS)
    if workspace_path:
        cfg_path = Path(workspace_path) / "coding_config.json"
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception as e:
                logger.warning("读取 coding_config.json 失败，使用默认值: %s", e)
    return cfg


def _get_workspace() -> str:
    """从会话上下文取 workspace_path。"""
    from novel_agent.chat.session_context import SessionContextManager
    ctx = SessionContextManager().get_context()
    return ctx.workspace_path if ctx else ""


def _validate_and_resolve_path(
    workspace_path: str, relative_path: str, sandbox_enabled: bool = True
) -> tuple[bool, str, Path | None]:
    """验证路径并解析为安全绝对路径。

    Returns:
        (success, error_message, resolved_path)
    """
    if not workspace_path:
        return False, "未配置 workspace 路径", None

    workspace = Path(workspace_path).resolve()
    if not workspace.exists():
        return False, f"Workspace 路径不存在: {workspace}", None

    if not sandbox_enabled:
        # 沙箱关闭：允许绝对路径，但仍拒绝敏感系统路径
        if os.path.isabs(relative_path):
            resolved = Path(relative_path).resolve()
        else:
            resolved = (workspace / relative_path).resolve()
        _SENSITIVE_DIRS = (
            Path("/etc"), Path("/proc"), Path("/sys"),
            Path("/dev"), Path("/boot"), Path("/root"),
        )
        for sensitive_dir in _SENSITIVE_DIRS:
            if resolved == sensitive_dir or resolved.is_relative_to(sensitive_dir):
                return False, f"沙箱关闭时仍禁止访问系统敏感路径: {resolved}", None
        return True, "", resolved

    if os.path.isabs(relative_path):
        return False, f"不允许使用绝对路径: {relative_path}", None

    resolved = (workspace / relative_path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        return False, f"路径穿越检测失败: {relative_path}", None

    # 符号链接逃逸检测
    real_path = Path(os.path.realpath(str(resolved)))
    try:
        real_path.relative_to(workspace)
    except ValueError:
        return False, "符号链接逃逸: 真实路径不在 workspace 内", None

    return True, "", resolved


def _check_file_size(path: Path, max_size: int) -> tuple[bool, str]:
    if path.exists() and path.is_file():
        size = path.stat().st_size
        if size > max_size:
            return False, f"文件大小 {size} bytes 超过限制 {max_size} bytes"
    return True, ""


def _search_with_ripgrep(
    search_dir: Path, regex: str, file_pattern: str, workspace_path: str
) -> str | None:
    """使用 ripgrep 搜索，不可用时返回 None。"""
    try:
        cmd = ["rg", "--json", "-e", regex]
        if file_pattern:
            cmd.extend(["-g", file_pattern])
        cmd.append(str(search_dir))

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, encoding="utf-8"
        )
        if result.returncode not in (0, 1):  # 1 = no matches
            return None

        matches: list[dict] = []
        total = 0
        workspace = Path(workspace_path).resolve()
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    total += 1
                    if len(matches) < _MAX_RIPGREP_RESULTS:
                        match_data = data["data"]
                        file_path = Path(match_data["path"]["text"])
                        try:
                            rel_path = str(file_path.relative_to(workspace))
                        except ValueError:
                            rel_path = str(file_path)
                        line_text = match_data["lines"]["text"].rstrip()
                        if len(line_text) > 500:
                            line_text = line_text[:500] + "..."
                        matches.append({
                            "file": rel_path,
                            "line": match_data["line_number"],
                            "content": line_text,
                        })
            except (json.JSONDecodeError, KeyError):
                continue

        return json.dumps(
            {"matches": matches, "total": total, "engine": "ripgrep"},
            ensure_ascii=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "搜索超时"}, ensure_ascii=False)


def _search_with_python(
    search_dir: Path, regex: str, file_pattern: str, workspace_path: str
) -> str:
    """Python 正则搜索降级实现。"""
    pattern = re.compile(regex)
    matches: list[dict] = []
    workspace = Path(workspace_path).resolve()
    max_results = 100

    for root, dirs, files in os.walk(search_dir):
        dirs[:] = [d for d in sorted(dirs) if d not in _SKIP_DIRS]
        for fname in files:
            if file_pattern and not fnmatch.fnmatch(fname, file_pattern):
                continue
            fpath = Path(root) / fname
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            try:
                                rel = str(fpath.relative_to(workspace))
                            except ValueError:
                                rel = str(fpath)
                            text = line.rstrip()
                            if len(text) > 500:
                                text = text[:500] + "..."
                            matches.append({"file": rel, "line": i, "content": text})
                            if len(matches) >= max_results:
                                break
            except (OSError, UnicodeDecodeError):
                continue
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    return json.dumps(
        {"matches": matches, "total": len(matches), "engine": "python"},
        ensure_ascii=False,
    )


def _get_patterns_for_suffix(suffix: str) -> list[tuple[re.Pattern, str]]:
    """根据文件后缀返回代码定义匹配模式。"""
    if suffix == ".py":
        return [
            (re.compile(r"^(?:async\s+)?def\s+(\w+)"), "function"),
            (re.compile(r"^class\s+(\w+)"), "class"),
        ]
    if suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
        return [
            (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"), "function"),
            (re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"), "class"),
            (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("), "function"),
            (re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)"), "interface"),
            (re.compile(r"^\s*(?:export\s+)?type\s+(\w+)"), "type"),
            (re.compile(r"^\s*(?:export\s+)?enum\s+(\w+)"), "enum"),
        ]
    if suffix in (".java", ".kt"):
        return [
            (re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:abstract\s+)?class\s+(\w+)"), "class"),
            (re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?interface\s+(\w+)"), "interface"),
            (re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:abstract\s+)?(?:\w+\s+)+(\w+)\s*\("), "method"),
        ]
    if suffix == ".go":
        return [
            (re.compile(r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)"), "function"),
            (re.compile(r"^type\s+(\w+)\s+struct"), "struct"),
            (re.compile(r"^type\s+(\w+)\s+interface"), "interface"),
        ]
    if suffix == ".rs":
        return [
            (re.compile(r"^\s*(?:pub\s+)?fn\s+(\w+)"), "function"),
            (re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)"), "struct"),
            (re.compile(r"^\s*(?:pub\s+)?enum\s+(\w+)"), "enum"),
            (re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)"), "trait"),
            (re.compile(r"^\s*impl\s+(\w+)"), "impl"),
        ]
    if suffix in (".c", ".h", ".cpp", ".hpp", ".cc"):
        return [
            (re.compile(r"^\s*(?:static\s+)?(?:inline\s+)?(?:\w+\s+)+(\w+)\s*\("), "function"),
            (re.compile(r"^\s*(?:typedef\s+)?struct\s+(\w+)"), "struct"),
            (re.compile(r"^\s*class\s+(\w+)"), "class"),
            (re.compile(r"^\s*namespace\s+(\w+)"), "namespace"),
        ]
    return []


def _extract_definitions(content: str, suffix: str) -> list[dict]:
    definitions: list[dict] = []
    patterns = _get_patterns_for_suffix(suffix)
    for i, line in enumerate(content.split("\n"), 1):
        for compiled_pattern, kind in patterns:
            match = compiled_pattern.match(line)
            if match:
                definitions.append({
                    "line": i,
                    "kind": kind,
                    "name": match.group(1) if match.groups() else "",
                    "text": line.rstrip()[:200],
                })
                break
    return definitions


# SEARCH/REPLACE 块正则
_SEARCH_REPLACE_PATTERN = re.compile(
    r"<<<<<<< SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n?>>>>>>> REPLACE",
    re.DOTALL,
)


def _walk_directory(
    abs_path: Path,
    workspace: Path,
    recursive: bool = True,
    include_dirs: bool = False,
    skip_hidden: bool = False,
    file_filter=None,
    max_entries: int = _MAX_DIR_ENTRIES,
) -> list[str]:
    """通用目录遍历：返回相对路径列表。"""
    entries: list[str] = []

    def _to_rel(full: Path) -> str:
        try:
            return str(full.relative_to(workspace))
        except ValueError:
            return str(full)

    if recursive:
        for root, dirs, files in os.walk(abs_path):
            dirs[:] = [d for d in sorted(dirs)
                       if d not in _SKIP_DIRS and (not skip_hidden or not d.startswith("."))]
            if include_dirs:
                for d in dirs:
                    entries.append(_to_rel(Path(root) / d) + "/")
                    if len(entries) >= max_entries:
                        break
            for fname in sorted(files):
                if skip_hidden and fname.startswith("."):
                    continue
                if file_filter and not file_filter(fname):
                    continue
                entries.append(_to_rel(Path(root) / fname))
                if len(entries) >= max_entries:
                    break
            if len(entries) >= max_entries:
                break
    else:
        for item in sorted(abs_path.iterdir()):
            if skip_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                if item.name in _SKIP_DIRS:
                    continue
                if include_dirs:
                    entries.append(_to_rel(item) + "/")
            else:
                if file_filter and not file_filter(item.name):
                    continue
                entries.append(_to_rel(item))
            if len(entries) >= max_entries:
                break

    return entries


# ═══════════════════════════════════════════════════════════════
# 10 个工具实现（统一 async -> str(JSON)）
# ═══════════════════════════════════════════════════════════════


async def read_file(path: str, offset: int = 0, limit: int = 0) -> str:
    """读取文件内容，支持行范围读取。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    if not abs_path.is_file():
        return json.dumps({"error": f"不是文件: {path}"}, ensure_ascii=False)
    ok, err = _check_file_size(abs_path, cfg["max_file_size"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)

    def _do_read():
        with open(abs_path, "rb") as f:
            chunk = f.read(8192)
        if b"\x00" in chunk:
            return (True, json.dumps(
                {"error": f"二进制文件不支持读取: {path}"}, ensure_ascii=False))
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return (False, f.readlines())

    try:
        is_binary, result_or_lines = await _run_io(_do_read)
        if is_binary:
            return result_or_lines
        lines = result_or_lines
        total_lines = len(lines)
        if offset > 0 or limit > 0:
            start = max(0, offset)
            end = start + limit if limit > 0 else total_lines
            selected = lines[start:end]
            numbered = [f"{i:6d}:{line.rstrip()}" for i, line in enumerate(selected, start=start + 1)]
            return json.dumps({
                "content": "\n".join(numbered),
                "total_lines": total_lines,
                "showing": f"lines {start + 1}-{min(end, total_lines)}",
            }, ensure_ascii=False)
        numbered = [f"{i:6d}:{line.rstrip()}" for i, line in enumerate(lines, start=1)]
        return json.dumps({
            "content": "\n".join(numbered),
            "total_lines": total_lines,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"读取文件失败: {e}"}, ensure_ascii=False)


async def write_to_file(path: str, content: str) -> str:
    """创建或覆盖整个文件。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)

    def _do_write():
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return len(content.encode("utf-8"))

    try:
        bytes_written = await _run_io(_do_write)
        return json.dumps(
            {"message": f"文件已写入: {path}", "bytes_written": bytes_written},
            ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"写入文件失败: {e}"}, ensure_ascii=False)


async def replace_in_file(path: str, old_str: str, new_str: str) -> str:
    """精确字符串替换（要求唯一匹配）。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    ok, err = _check_file_size(abs_path, cfg["max_file_size"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)

    def _do_read():
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    try:
        original_content = await _run_io(_do_read)
    except Exception as e:
        return json.dumps({"error": f"替换失败: {e}"}, ensure_ascii=False)

    try:
        if old_str not in original_content:
            normalized_content = original_content.replace("\r\n", "\n")
            normalized_old = old_str.replace("\r\n", "\n")
            if normalized_old not in normalized_content:
                return json.dumps({"error": "未找到要替换的文本"}, ensure_ascii=False)
            norm_count = normalized_content.count(normalized_old)
            if norm_count > 1:
                return json.dumps(
                    {"error": f"找到 {norm_count} 处匹配（归一化后），old_str 不唯一，请提供更多上下文"},
                    ensure_ascii=False)
            new_content = normalized_content.replace(
                normalized_old, new_str.replace("\r\n", "\n"), 1)
        else:
            count = original_content.count(old_str)
            if count > 1:
                return json.dumps(
                    {"error": f"找到 {count} 处匹配，old_str 不唯一，请提供更多上下文使其唯一"},
                    ensure_ascii=False)
            new_content = original_content.replace(old_str, new_str, 1)

        def _do_write():
            with open(abs_path, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)
        await _run_io(_do_write)
        return json.dumps(
            {"message": f"文件已更新: {path}", "replacements": 1}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"替换失败: {e}"}, ensure_ascii=False)


async def search_files(path: str, regex: str, file_pattern: str = "") -> str:
    """内容正则搜索（ripgrep 优先，Python 降级）。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"路径不存在: {path}"}, ensure_ascii=False)

    def _do_search():
        rg = _search_with_ripgrep(abs_path, regex, file_pattern, workspace_path)
        if rg is not None:
            return rg
        return _search_with_python(abs_path, regex, file_pattern, workspace_path)

    try:
        return await _run_io(_do_search)
    except Exception as e:
        return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)


async def search_file(
    path: str, pattern: str, recursive: bool = True, caseSensitive: bool = False
) -> str:
    """按文件名 glob 模式搜索文件。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"路径不存在: {path}"}, ensure_ascii=False)
    if not abs_path.is_dir():
        return json.dumps({"error": f"不是目录: {path}"}, ensure_ascii=False)

    workspace = Path(workspace_path).resolve()
    match_pattern = pattern if caseSensitive else pattern.lower()

    def _file_filter(fname: str) -> bool:
        name = fname if caseSensitive else fname.lower()
        return fnmatch.fnmatch(name, match_pattern)

    def _do_search_file():
        return _walk_directory(
            abs_path, workspace, recursive=recursive,
            skip_hidden=True, file_filter=_file_filter)

    try:
        entries = await _run_io(_do_search_file)
        return json.dumps({
            "matches": entries, "total": len(entries),
            "truncated": len(entries) >= _MAX_DIR_ENTRIES, "pattern": pattern,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"搜索文件失败: {e}"}, ensure_ascii=False)


async def list_files(path: str, recursive: bool = True) -> str:
    """列出目录结构。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"路径不存在: {path}"}, ensure_ascii=False)
    if not abs_path.is_dir():
        return json.dumps({"error": f"不是目录: {path}"}, ensure_ascii=False)

    workspace = Path(workspace_path).resolve()

    def _do_list():
        return _walk_directory(abs_path, workspace, recursive=recursive, include_dirs=True)

    try:
        entries = await _run_io(_do_list)
        return json.dumps({
            "entries": entries, "total": len(entries),
            "truncated": len(entries) >= _MAX_DIR_ENTRIES,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"列出目录失败: {e}"}, ensure_ascii=False)


async def list_code_definitions(path: str) -> str:
    """列出代码文件中的定义（函数、类、方法等）。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    ok, err = _check_file_size(abs_path, cfg["max_file_size"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)

    def _do_parse():
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return _extract_definitions(content, abs_path.suffix.lower())

    try:
        definitions = await _run_io(_do_parse)
        return json.dumps(
            {"file": path, "definitions": definitions, "total": len(definitions)},
            ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"解析代码定义失败: {e}"}, ensure_ascii=False)


async def apply_diff(path: str, diff: str) -> str:
    """SEARCH/REPLACE 块批量编辑（支持多块、宽松匹配、空白模糊匹配）。"""
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    ok, err, abs_path = _validate_and_resolve_path(
        workspace_path, path, cfg["path_sandbox_enabled"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)
    if not abs_path.exists():
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    ok, err = _check_file_size(abs_path, cfg["max_file_size"])
    if not ok:
        return json.dumps({"error": err}, ensure_ascii=False)

    def _do_read():
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    try:
        original_content = await _run_io(_do_read)
    except Exception as e:
        return json.dumps({"error": f"读取文件失败: {e}"}, ensure_ascii=False)

    blocks = list(_SEARCH_REPLACE_PATTERN.finditer(diff))
    if not blocks:
        return json.dumps(
            {"error": "未找到有效的 SEARCH/REPLACE 块。"
             "请使用格式: <<<<<<< SEARCH\\n原始代码\\n=======\\n新代码\\n>>>>>>> REPLACE"},
            ensure_ascii=False)

    current_content = original_content
    results: list[dict] = []

    for idx, match in enumerate(blocks):
        search_text = match.group(1)
        replace_text = match.group(2)
        block_info = {"index": idx, "success": False, "message": ""}

        if not search_text.strip():
            block_info["message"] = f"第 {idx + 1} 块：SEARCH 部分为空，已跳过"
            results.append(block_info)
            continue

        # 1) 精确匹配
        if search_text in current_content:
            count = current_content.count(search_text)
            if count > 1:
                block_info["message"] = (
                    f"第 {idx + 1} 块：SEARCH 文本匹配到 {count} 处，请提供更多上下文使其唯一")
                results.append(block_info)
                continue
            current_content = current_content.replace(search_text, replace_text, 1)
            block_info["success"] = True
            block_info["message"] = f"第 {idx + 1} 块：已应用"
            results.append(block_info)
            continue

        # 2) 宽松匹配（strip 首尾空白）
        search_stripped = search_text.strip()
        if search_stripped and search_stripped in current_content:
            count = current_content.count(search_stripped)
            if count > 1:
                block_info["message"] = (
                    f"第 {idx + 1} 块：宽松匹配后仍匹配到 {count} 处，请提供更多上下文")
                results.append(block_info)
                continue
            current_content = current_content.replace(
                search_stripped, replace_text.strip() or replace_text, 1)
            block_info["success"] = True
            block_info["message"] = f"第 {idx + 1} 块：已应用（宽松匹配）"
            results.append(block_info)
            continue

        # 3) 空白模糊匹配
        _WS = "\x00WS\x00"
        parts = re.split(r"(\s+)", search_text)
        escaped = [
            _WS if re.fullmatch(r"\s+", p) else re.escape(p) for p in parts
        ]
        fuzzy_pattern = "".join(escaped).replace(_WS, r"\s+")
        try:
            fmatch = re.compile(fuzzy_pattern).search(current_content)
            if fmatch:
                current_content = current_content.replace(fmatch.group(0), replace_text, 1)
                block_info["success"] = True
                block_info["message"] = f"第 {idx + 1} 块：已应用（空白宽松匹配）"
                results.append(block_info)
                continue
        except re.error:
            pass

        first_line = search_text.strip().split("\n")[0][:80]
        block_info["message"] = (
            f"第 {idx + 1} 块：未找到 SEARCH 文本。搜索起始内容: '{first_line}...'。"
            f"请使用 read_file 查看当前文件内容后重试。")
        results.append(block_info)

    succeeded = sum(1 for r in results if r["success"])
    if succeeded > 0:
        def _do_write():
            with open(abs_path, "w", encoding="utf-8", newline="") as f:
                f.write(current_content)
        try:
            await _run_io(_do_write)
        except Exception as e:
            return json.dumps({"error": f"写入文件失败: {e}"}, ensure_ascii=False)

    return json.dumps({
        "file": path, "blocks": results,
        "total": len(results), "succeeded": succeeded,
        "failed": len(results) - succeeded,
    }, ensure_ascii=False)


# 高风险命令模式（需要审批）
_RISKY_CMD_PATTERNS = [
    r"\brm\s+-rf\b", r"\bdel\s+/[sfq]", r"\bformat\b", r"\bmkfs\b",
    r"\bdd\s+if=", r">\s*/dev/", r"\bshutdown\b", r"\breboot\b",
    r"\bgit\s+push\s+.*--force", r"\bgit\s+reset\s+--hard",
    r"\bDROP\s+TABLE\b", r"\bTRUNCATE\b",
]


async def execute_command(
    command: str, cwd: str = "", approval_callback: Any = None
) -> str:
    """执行终端命令。高风险命令需审批（通过 approval_callback 异步确认）。

    Args:
        command: 要执行的命令
        cwd: 工作目录（相对 workspace）
        approval_callback: 可选异步回调 (command: str) -> bool，返回 True 表示批准
    """
    workspace_path = _get_workspace()
    cfg = _get_coding_config(workspace_path)
    if not cfg["tools_enabled"]:
        return json.dumps({"error": "编码工具已禁用"}, ensure_ascii=False)
    if not workspace_path:
        return json.dumps({"error": "未配置 workspace 路径"}, ensure_ascii=False)

    workspace = Path(workspace_path).resolve()
    if cwd:
        ok, err, work_dir = _validate_and_resolve_path(
            workspace_path, cwd, cfg["path_sandbox_enabled"])
        if not ok:
            return json.dumps({"error": err}, ensure_ascii=False)
    else:
        work_dir = workspace

    # 高风险命令检测 → 审批
    is_risky = any(re.search(p, command, re.IGNORECASE) for p in _RISKY_CMD_PATTERNS)
    if is_risky:
        if approval_callback is None:
            return json.dumps(
                {"error": f"命令命中高风险模式，需要审批但无审批通道: {command}",
                 "exit_code": -1},
                ensure_ascii=False)
        approved = await approval_callback(command)
        if not approved:
            return json.dumps(
                {"error": f"命令审批被拒绝: {command}", "exit_code": -1},
                ensure_ascii=False)

    timeout = cfg["cmd_timeout"]

    def _run_command():
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return subprocess.run(
            command, shell=True, cwd=str(work_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=creationflags)

    try:
        result = await _run_io(_run_command)
        stdout_str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr_str = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        output = stdout_str
        if stderr_str:
            output += ("\n--- stderr ---\n" if output else "") + stderr_str
        if len(output) > 10000:
            output = output[:10000] + "\n... (输出已截断)"
        return json.dumps(
            {"exit_code": result.returncode, "output": output, "command": command},
            ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"error": f"命令执行超时 ({timeout}s): {command}", "exit_code": -1},
            ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            {"error": f"命令执行失败: {e}", "exit_code": -1}, ensure_ascii=False)


async def ask_user(question: str) -> str:
    """向用户提问等待确认（返回 needs_user_input 标记，由上层暂停流程）。"""
    from novel_agent.chat.session_context import SessionContextManager
    ctx = SessionContextManager().get_context()
    return json.dumps({
        "needs_user_input": True,
        "question": question,
        "session_id": ctx.session_id if ctx else "",
    }, ensure_ascii=False)


# ── OpenAI function calling schema ────────────────────────────

CODING_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文件内容。支持行范围读取。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 workspace）"},
            "offset": {"type": "integer", "description": "起始行号（从 0 开始）", "default": 0},
            "limit": {"type": "integer", "description": "读取行数（0 表示全部）", "default": 0},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_to_file",
        "description": "创建或覆盖整个文件。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 workspace）"},
            "content": {"type": "string", "description": "文件内容"},
        }, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "replace_in_file",
        "description": "在文件中进行搜索替换编辑（精确字符串匹配，要求唯一匹配）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 workspace）"},
            "old_str": {"type": "string", "description": "要替换的旧文本"},
            "new_str": {"type": "string", "description": "替换后的新文本"},
        }, "required": ["path", "old_str", "new_str"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "在文件内容中进行正则搜索（自动尝试 ripgrep，不可用则降级为 Python）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "搜索根目录（相对于 workspace）"},
            "regex": {"type": "string", "description": "正则表达式模式"},
            "file_pattern": {"type": "string", "description": "文件名 glob 过滤（如 '*.py'）", "default": ""},
        }, "required": ["path", "regex"]}}},
    {"type": "function", "function": {
        "name": "search_file",
        "description": "按文件名 glob 模式搜索文件（区别于 search_files 按内容搜索）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "搜索根目录（相对于 workspace）"},
            "pattern": {"type": "string", "description": "文件名 glob 模式"},
            "recursive": {"type": "boolean", "default": True},
            "caseSensitive": {"type": "boolean", "default": False},
        }, "required": ["path", "pattern"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "列出目录结构。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径（相对于 workspace）"},
            "recursive": {"type": "boolean", "default": True},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_code_definitions",
        "description": "列出代码文件中的定义（函数、类、方法等）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 workspace）"},
        }, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "apply_diff",
        "description": "使用 SEARCH/REPLACE 块格式批量编辑文件。格式: <<<<<<< SEARCH\\n原始代码\\n=======\\n新代码\\n>>>>>>> REPLACE。支持多块批量处理与空白模糊匹配。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件路径（相对于 workspace）"},
            "diff": {"type": "string", "description": "SEARCH/REPLACE 块内容"},
        }, "required": ["path", "diff"]}}},
    {"type": "function", "function": {
        "name": "execute_command",
        "description": "执行终端命令。高风险命令需要用户审批后才能执行。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的终端命令"},
            "cwd": {"type": "string", "description": "工作目录（相对于 workspace）", "default": ""},
        }, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "ask_user",
        "description": "向用户提问等待确认。",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "要向用户提出的问题"},
        }, "required": ["question"]}}},
]

# 工具名 -> 实现函数映射（供注册层使用）
CODING_TOOLS_IMPL: dict[str, Any] = {
    "read_file": read_file,
    "write_to_file": write_to_file,
    "replace_in_file": replace_in_file,
    "search_files": search_files,
    "search_file": search_file,
    "list_files": list_files,
    "list_code_definitions": list_code_definitions,
    "apply_diff": apply_diff,
    "execute_command": execute_command,
    "ask_user": ask_user,
}
