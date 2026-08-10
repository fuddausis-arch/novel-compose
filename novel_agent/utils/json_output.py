"""JSON 输出校验 + 安全修复流水线。

借鉴 DeterminFlow json_output.py 的 5 策略修复：
1. strip_fence: 去除 ```json ... ``` 围栏
2. normalize_quotes: 中文引号 -> ASCII 直引号
3. extract_body: 从混合文本中提取 JSON 主体（找第一个 { 到最后一个 }）
4. fix_trailing_comma: 去除尾逗号
5. escape_newlines: 转义字符串中的裸换行

如果 5 策略都修复不了，返回 None（调用方可以触发模型重试）。

与 novel_agent.utils.json_parser.parse_json_strict 的关系：
- parse_json_safe 是更强大的版本，返回 dict | None（不静默返回 {}）
- parse_json_strict 内部会优先调用 parse_json_safe，失败再走原有兜底逻辑
"""
from __future__ import annotations

import html
import json
import logging
import re
from json import JSONDecodeError

logger = logging.getLogger(__name__)


# ── 5 个独立修复策略（可单独调用）──────────────────────────


def strip_fence(text: str) -> str:
    """策略1：去除 ```json ... ``` 围栏。

    兼容只有开头围栏没有结尾、以及散落 ``` 行的情况。
    """
    stripped = text.strip()
    # 完整围栏：```json\n...\n```
    match = re.fullmatch(r"```(?:json|JSON)?\s*\n?(.*?)\n?```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    # 散落的 ``` 行（开头围栏但无结尾）：逐行移除 ``` 标记行
    if "```" in stripped:
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        return "\n".join(lines).strip()
    return stripped


def normalize_quotes(text: str) -> str:
    """策略2：中文引号 -> ASCII 直引号。

    中文 LLM 常在 JSON 结构中误用全角引号，导致 json.loads 失败。
    只替换结构性引号字符，保留字符串内部内容语义。
    """
    return (
        text.replace("\u201c", '"')  # “
        .replace("\u201d", '"')  # ”
        .replace("\uff02", '"')  # ＂
        .replace("\u2018", "'")  # ‘
        .replace("\u2019", "'")  # ’
        .replace("\uff07", "'")  # ＇
    )


def extract_body(text: str) -> str:
    """策略3：从混合文本中提取 JSON 主体。

    找第一个 { 到最后一个 }（或第一个 [ 到最后一个 ]），
    适用于 LLM 在 JSON 前后夹杂解释文字的场景。
    """
    start = text.find("{")
    obj_end = text.rfind("}")
    arr_start = text.find("[")
    arr_end = text.rfind("]")

    # 优先选 { } 主体
    if start != -1 and obj_end != -1 and obj_end > start:
        return text[start : obj_end + 1].strip()
    # 退而求其次选 [ ] 数组
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        return text[arr_start : arr_end + 1].strip()
    return text.strip()


def fix_trailing_comma(text: str) -> str:
    """策略4：去除尾逗号（,} 与 ,]）。

    循环移除直到稳定，处理多层嵌套的尾逗号。
    仅在字符串外部清理，避免误伤字符串内部的 ", }" 文本。
    """
    # 先用状态机保护字符串内部，仅在结构层移除尾逗号
    return _remove_trailing_commas_safe(text)


def _remove_trailing_commas_safe(text: str) -> str:
    """仅在字符串外部移除尾逗号（,} 与 ,]），保留字符串内部内容。"""
    result: list[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if escape:
            escape = False
            result.append(ch)
            i += 1
            continue
        if ch == "\\":
            escape = True
            result.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if not in_string and ch == ",":
            # 跳过逗号后的空白，若紧跟 } 或 ] 则视为尾逗号，移除逗号
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # 跳过这个逗号（不写入结果）
                continue
        result.append(ch)
        i += 1
    return "".join(result)


def escape_newlines(text: str) -> str:
    """策略5：转义字符串中的裸换行。

    JSON 规范要求字符串内的换行必须转义为 \\n，
    但 LLM 常直接输出裸换行导致 json.loads 失败。
    只处理被 " 包裹的字符串内部换行，不动结构部分的换行。
    """
    result: list[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if escape:
            escape = False
            result.append(ch)
            i += 1
            continue
        if ch == "\\":
            escape = True
            result.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if in_string:
            # 字符串内部：\r\n / \r / \n -> 转义为 \n（字面反斜杠+n）
            if ch == "\r":
                result.append("\\n")
                i += 1
                continue
            if ch == "\n":
                result.append("\\n")
                i += 1
                continue
        result.append(ch)
        i += 1
    return "".join(result)


# ── 策略元信息（用于日志记录修复了哪些策略）──────────────────

# 每个策略：(策略名, 函数, 是否幂等)
# strip_fence / normalize_quotes / extract_body 改变文本范围，需顺序执行；
# fix_trailing_comma / escape_newlines 是局部替换，幂等。
_REPAIR_STRATEGIES: list[tuple[str, callable]] = [
    ("strip_fence", strip_fence),
    ("normalize_quotes", normalize_quotes),
    ("extract_body", extract_body),
    ("fix_trailing_comma", fix_trailing_comma),
    ("escape_newlines", escape_newlines),
]


def _decode_html_entities(text: str) -> str:
    """循环解码 HTML 实体直到稳定，处理双重/多重转义（&amp;amp; → &）。"""
    prev = None
    while prev != text:
        prev = text
        text = html.unescape(text)
    return text


def _try_loads(text: str) -> dict | None:
    """尝试解析 JSON，成功返回 dict（数组包装为 {"_list": [...]}），失败返回 None。"""
    try:
        data = json.loads(text)
    except JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"_list": data}
    return None


# ── 主接口 ─────────────────────────────────────────────────


def parse_json_safe(raw: str) -> dict | None:
    """依次尝试 5 策略修复并解析 JSON。

    流程：
    1. 直接解析原文（可能本就是合法 JSON）
    2. 依次叠加 5 个修复策略，每叠加一个就尝试解析
    3. 全部失败则返回 None

    Args:
        raw: LLM 原始输出文本

    Returns:
        解析后的 dict；解析失败返回 None（调用方可触发模型重试）
    """
    if not raw or not raw.strip():
        logger.debug("parse_json_safe: 输入为空")
        return None

    # 0. 解码 HTML 实体（部分模型/网关会返回 &quot; &amp; 等转义，甚至双重转义）
    # 循环解码直到稳定，处理 &amp;amp; 这类双重转义；& 是 JSON 字符串合法字符，解码不影响结构
    raw = _decode_html_entities(raw)

    # 先尝试直接解析
    result = _try_loads(raw)
    if result is not None:
        logger.debug("parse_json_safe: 原文直接解析成功（无需修复）")
        return result

    # 依次叠加 5 个修复策略
    candidate = raw
    applied: list[str] = []
    for name, strategy in _REPAIR_STRATEGIES:
        candidate = strategy(candidate)
        result = _try_loads(candidate)
        if result is not None:
            applied.append(name)
            logger.info("parse_json_safe: 修复成功，应用策略=%s", "+".join(applied))
            return result
        applied.append(name)

    logger.warning(
        "parse_json_safe: 5 策略全部失败，输入前200字: %s", raw[:200]
    )
    return None


async def parse_json_with_retry(
    raw: str,
    llm_client,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 1,
) -> dict | None:
    """修复失败后让 LLM 重新输出 JSON。

    先用 parse_json_safe 尝试修复；失败则把错误上下文喂给 LLM 让其重新输出，
    再次用 parse_json_safe 解析。最多重试 max_retries 次。

    Args:
        raw: LLM 原始输出文本
        llm_client: LLMClient 实例（需有 async generate 方法）
        system_prompt: 重试时使用的 system prompt
        user_prompt: 重试时使用的 user prompt（原始请求）
        max_retries: 最大重试次数，默认 1

    Returns:
        解析后的 dict；全部失败返回 None
    """
    # 先尝试修复原文
    result = parse_json_safe(raw)
    if result is not None:
        return result

    last_raw = raw
    for attempt in range(max_retries):
        # 构建重试提示：告诉模型上一次输出非法，要求只返回 JSON
        retry_hint = _build_retry_prompt(last_raw)
        try:
            new_raw = await llm_client.generate(
                user_content=f"{user_prompt}\n\n{retry_hint}",
                system=system_prompt,
            )
        except Exception as e:
            logger.warning("parse_json_with_retry: LLM 重试调用失败(尝试%d): %s", attempt + 1, e)
            return None

        result = parse_json_safe(new_raw)
        if result is not None:
            logger.info("parse_json_with_retry: 第 %d 次重试修复成功", attempt + 1)
            return result
        last_raw = new_raw
        logger.warning(
            "parse_json_with_retry: 第 %d 次重试仍失败", attempt + 1
        )

    return None


def _build_retry_prompt(bad_output: str) -> str:
    """构建让 LLM 重新输出合法 JSON 的提示。"""
    # 截取错误输出片段，避免过长
    snippet = bad_output[:500] if bad_output else ""
    return (
        "你的上一次输出不是合法 JSON，请重新输出。\n\n"
        "上一次输出（片段）：\n"
        f"{snippet}\n\n"
        "要求：\n"
        "1. 只返回修复后的完整 JSON 对象，不要输出 Markdown 围栏、解释或注释。\n"
        "2. 使用 ASCII 直引号，不要用中文引号。\n"
        "3. 不要有尾逗号。\n"
        "4. 字符串内的换行用 \\n 转义。"
    )
