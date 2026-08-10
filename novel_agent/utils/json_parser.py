"""统一的 JSON 提取与校验工具（B8修复）。

替代散落在 5 个文件中的 _extract_json 实现，消除行为不一致与静默失败。
"""
from __future__ import annotations

import html
import json
import logging
import re

logger = logging.getLogger(__name__)

# 全局解析失败计数（供 metrics 采集）
_parse_failures = 0


def parse_json_strict(text: str, *, default: dict | None = None) -> dict:
    """从 LLM 输出提取 JSON 对象。

    统一流程：
    1. 剥离 ``` 围栏 + 前言/尾注
    2. 正则提取平衡括号匹配的 {...}
    3. json.loads 解析
    4. 失败计数上报（不静默返回 {} 让下游误以为成功）

    Args:
        text: LLM 原始输出
        default: 解析失败时的返回值（默认 {} ）

    Returns:
        解析后的 dict，失败时返回 default
    """
    global _parse_failures
    if default is None:
        default = {}

    if not text or not text.strip():
        _parse_failures += 1
        logger.warning("parse_json_strict: 输入为空")
        return default

    # 0. 优先调用更强的 parse_json_safe（5 策略修复流水线）
    # 若成功则直接返回，避免重复劳动；失败则继续走原有兜底逻辑
    from novel_agent.utils.json_output import parse_json_safe

    safe_result = parse_json_safe(text)
    if safe_result is not None:
        return safe_result

    # 1. 剥离代码块围栏
    candidate = _strip_code_fence(text)

    # 1.5 预处理常见LLM JSON格式问题（先替换全角引号/标点，使后续步骤基于标准引号判断字符串边界）
    candidate = _sanitize_json_text(candidate)

    # 2. 尝试直接解析
    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"_list": result}
    except json.JSONDecodeError:
        pass

    # 3. 平衡括号匹配
    extracted = _balanced_bracket_extract(candidate)
    if extracted:
        try:
            result = json.loads(extracted)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 3.5 修复截断/不规范的JSON：逐个提取完整的子对象
    repaired = _repair_and_extract(candidate)
    if repaired:
        return repaired

    # 3.6 尝试 json5（宽松JSON解析，支持尾逗号/单引号/注释等）
    try:
        import json5
        for attempt_text in [candidate, extracted or ""]:
            if not attempt_text:
                continue
            result = json5.loads(attempt_text)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"_list": result}
    except Exception:
        pass

    # 4. 尝试 ast.literal_eval（处理LLM返回的Python风格单引号dict）
    import ast
    for attempt_text in [candidate, extracted or ""]:
        if not attempt_text:
            continue
        try:
            result = ast.literal_eval(attempt_text)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"_list": result}
        except (ValueError, SyntaxError):
            pass

    # 5. 失败
    _parse_failures += 1
    logger.warning("parse_json_strict: JSON 解析失败，输入前200字: %s", text[:200])
    return default


def _strip_code_fence(text: str) -> str:
    """剥离 ```json...``` 围栏和常见前言/尾注。"""
    text = text.strip()
    # 剥离代码块：优先匹配 ```json ... ```（结束围栏取最后一个 ```，
    # 避免 JSON 字符串内部出现 ``` 导致截断），也兼容只有开头 ``` 没有结尾的情况
    if text.startswith("```"):
        end = text.rfind("```")
        if end > 3:
            inner = text[3:end]
            inner = re.sub(r"^\s*(?:json|JSON)?\s*", "", inner, count=1)
            body = inner.strip()
            if body.startswith("{") or body.startswith("["):
                return body
    # 只有开头围栏或无 { [ 开头：移除围栏行
    if text.startswith("```") or "```" in text[:30]:
        return re.sub(r"^```(?:json|JSON)?\s*\n?", "", text, flags=re.IGNORECASE).strip()
    # 剥离前言（"好的，以下是..." / "以下是..."）
    text = re.sub(r'^(好的[，,]?\s*|以下是|这是|输出如下[：:])', '', text)
    # 剥离尾注（"希望您喜欢" / "以上是..."）
    text = re.sub(r'(希望您喜欢[！!。]?\s*$|以上是.*?$)', '', text)
    return text.strip()


def _sanitize_json_text(text: str) -> str:
    r"""预处理LLM常见的JSON格式问题。

    处理：
    1. 全角标点 → 半角（中文LLM常见问题：在JSON中用了中文标点），同时维护字符串状态
    2. // 单行注释（JSON不支持）
    3. \\uXXXX 双反斜杠unicode escape → \uXXXX
    4. \\UXXXXXXXX Python风格unicode → 移除（非JSON标准）
    5. 控制字符（\x00-\x1f）→ 移除
    """
    # 0. 解码 HTML 实体（部分模型/网关会返回 &quot; &amp; 等转义）
    # 循环解码直到稳定，处理双重转义
    prev = None
    while prev != text:
        prev = text
        text = html.unescape(text)

    # 全角标点 → 半角（中文LLM常见问题：在JSON中用了中文标点）
    # 必须在其他基于字符串边界的处理之前执行，确保后续步骤能正确识别 JSON 字符串范围
    text = _replace_fullwidth_punct(text)

    # 移除 // 单行注释（仅在字符串外部）
    lines = text.split("\n")
    cleaned_lines = []
    in_string = False
    escape = False
    for line in lines:
        result = []
        i = 0
        while i < len(line):
            ch = line[i]
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
            if not in_string and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                # 跳过注释到行尾
                break
            result.append(ch)
            i += 1
        cleaned_lines.append("".join(result))
    text = "\n".join(cleaned_lines)

    # 修复 \\uXXXX → \uXXXX（双反斜杠unicode escape）
    text = re.sub(r'\\\\u([0-9a-fA-F]{4})', r'\\u\1', text)
    # 移除 \\UXXXXXXXX（Python风格8位unicode escape，非JSON标准）
    text = re.sub(r'\\U[0-9a-fA-F]{8}', '', text)
    # 转义字符串内部的裸换行符（JSON 规范要求字符串内换行必须转义）
    text = _escape_newlines_in_strings(text)
    # 移除控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    return text


def _replace_fullwidth_punct(text: str) -> str:
    r"""将全角标点替换为半角，并维护正确的字符串状态。

    中文LLM常在JSON结构中使用全角标点：
    ，→,  ：→:  " "→" "  （→(  ）→)  ；→;  。→.  【→[ 】→]
    特别地，全角引号替换为半角引号时，必须同步切换 in_string 状态，
    否则后续基于字符串边界的处理（如换行转义、注释移除）会失效。
    """
    # 结构字符：只在字符串外部替换；字符串内部保留原样避免破坏内容。
    # 引号：替换时同步切换 in_string 状态。
    fullwidth_map = {
        "\uff0c": ",",  # ，
        "\uff1a": ":",  # ：
        "\uff08": "(",  # （
        "\uff09": ")",  # ）
        "\uff1b": ";",  # ；
        "\u3002": ".",  # 。
        "\u3001": ",",  # 、
        "\u3010": "[",  # 【
        "\u3011": "]",  # 】
        "\uff3b": "[",  # ［
        "\uff3d": "]",  # ］
        "\uff5b": "{",  # ｛
        "\uff5d": "}",  # ｝
        "\uff1f": "?",  # ？
        "\uff01": "!",  # ！
        "\u201c": '"',  # "
        "\u201d": '"',  # "
        "\u2018": "'",  # ‘
        "\u2019": "'",  # ’
        "\uff02": '"',  # ＂
        "\uff07": "'",  # ＇
    }
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            result.append(ch)
            continue
        if ch == "\\":
            escape = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if ch in fullwidth_map:
            replacement = fullwidth_map[ch]
            # 全角引号处理：字符串外部替换成半角引号并切换状态；
            # 字符串内部保留原样，避免破坏 JSON 字符串边界（LLM 常在 summary 中用“”）。
            if replacement == '"':
                if in_string:
                    result.append(ch)
                else:
                    in_string = not in_string
                    result.append(replacement)
                continue
            if replacement == "'":
                # 单引号不是 JSON 定界符，字符串外翻转 in_string 会破坏状态机；
                # 统一保留原文，字符串内外都按普通字符处理
                result.append(ch)
                continue
            if not in_string:
                # 结构字符仅在字符串外部才需要替换
                result.append(replacement)
                continue
            # 字符串内部的结构类全角标点保留原文，避免破坏内容语义
            result.append(ch)
            continue
        result.append(ch)
    return "".join(result)


def _escape_newlines_in_strings(text: str) -> str:
    r"""在 JSON 字符串内部把裸换行符转义为 \n。

    JSON 规范要求字符串内的换行必须转义为 \n，
    但 LLM 常直接输出裸换行（\n / \r / \r\n），导致 json.loads 失败。
    只处理字符串内部（被 " 包裹）的换行，不动结构部分的换行。
    """
    result = []
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
            # 字符串内部：\r\n / \r / \n → 转义为 \n（字面反斜杠+n）
            if ch == "\r":
                if i + 1 < n and text[i + 1] == "\n":
                    result.append("\\n")
                    i += 2
                    continue
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


def _repair_and_extract(text: str) -> dict | None:
    """修复截断/不规范的JSON，尝试提取有效数据。
    
    策略：
    1. 优先识别常见数组关键字（chapters/arcs/sections/volumes/characters/world_settings 等）
    2. 找到所有完整的 {...} 子对象（平衡括号匹配）
    3. 对每个子对象尝试 json.loads
    4. 如果找到目标数组结构，组装返回
    """
    # 常见数组字段名，覆盖大纲/设定/角色/世界观/状态增量/事件/伏笔等生成接口
    array_keys = [
        "arcs", "sections", "chapters", "volumes",
        "characters", "chars", "roles",
        "world_settings", "worlds", "settings",
        "factions", "monsters", "relationships",
        "state_deltas", "deltas",
        "events",
        "foreshadow_updates", "resolved_foreshadows",
        "new_characters", "new_factions", "new_monsters", "new_world_settings",
        "beats_delivered",
        "outlines", "summaries",
    ]
    for key in array_keys:
        pattern = rf'"{key}"\s*:\s*\['
        match = re.search(pattern, text)
        if match:
            arr_start = match.end() - 1  # 指向 [
            items = _extract_complete_objects(text, arr_start)
            if items:
                return {key: items}
    
    # 没有识别到已知数组结构，尝试提取所有完整对象
    objects = _extract_all_complete_objects(text)
    if objects:
        # 如果只有一个对象，直接返回
        if len(objects) == 1:
            return objects[0]
        # 多个对象，包装为列表
        return {"_list": objects}
    
    return None


def _extract_complete_objects(text: str, arr_start: int) -> list:
    """从数组起始位置提取所有完整的 {...} 对象。"""
    objects = []
    i = arr_start + 1  # 跳过 [
    depth = 0
    obj_start = -1
    in_string = False
    escape = False
    
    while i < len(text):
        ch = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            i += 1
            continue
        if in_string:
            i += 1
            continue
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                obj_text = text[obj_start:i + 1]
                parsed = _try_parse_object(obj_text)
                if parsed:
                    objects.append(parsed)
                obj_start = -1
        elif ch == "]" and depth == 0:
            break
        i += 1
    
    return objects


def _extract_all_complete_objects(text: str) -> list:
    """从文本中提取所有完整的 {...} 对象。"""
    objects = []
    i = 0
    depth = 0
    obj_start = -1
    in_string = False
    escape = False
    
    while i < len(text):
        ch = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            i += 1
            continue
        if in_string:
            i += 1
            continue
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                obj_text = text[obj_start:i + 1]
                parsed = _try_parse_object(obj_text)
                if parsed:
                    objects.append(parsed)
                obj_start = -1
        i += 1
    
    return objects


def _remove_trailing_commas(text: str) -> str:
    """仅在字符串外部移除尾逗号（,} 与 ,]），保留字符串内部内容。

    原 re.sub(r',\s*}', '}', ...) 会误伤字符串内部的 ", }" 文本，
    这里用状态机扫描保证只在 JSON 结构层清理。
    """
    result = []
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
                i += 1
                continue
        result.append(ch)
        i += 1
    return "".join(result)


def _try_parse_object(obj_text: str) -> dict | None:
    """尝试多种方式解析单个 JSON 对象，返回 dict 或 None。"""
    # 1. 直接解析
    try:
        obj = json.loads(obj_text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. 标准化清洗后再解析（处理对象内部的中文标点、裸换行等）
    cleaned = _sanitize_json_text(obj_text)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 3. 移除尾逗号、多余空白后再解析（仅字符串外，避免误伤字符串内容）
    cleaned = _remove_trailing_commas(obj_text)
    cleaned = re.sub(r'\n+', ' ', cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 4. 对移除尾逗号后的文本再跑一遍标准化
    cleaned = _sanitize_json_text(cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    return None


def _balanced_bracket_extract(text: str) -> str | None:
    """用平衡括号匹配提取第一个完整的 {...}。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def get_parse_failure_count() -> int:
    """获取累计解析失败次数（供 metrics 采集）。"""
    return _parse_failures


def reset_parse_failure_count() -> None:
    """重置失败计数。"""
    global _parse_failures
    _parse_failures = 0
