"""节点级工具权限控制。

借鉴 DeterminFlow tool_guard.py：
- 每个 Agent 角色配置可见工具白名单/黑名单
- 工具注册时检查权限，不在白名单的工具不暴露给 LLM
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 角色工具白名单：角色 -> 允许使用的工具名列表
# 借鉴 DeterminFlow tool_guard.py 的 PermissionGuard 思路：
# 每个角色只能看到其职责范围内的工具，防止越权操作
TOOL_WHITELIST: dict[str, list[str]] = {
    # 写手：只读章节/大纲/设定/世界状态，不写库
    "writer": ["read_chapter", "read_outline", "read_bible", "read_world_state"],
    # 审校：只读章节/设定/伏笔/时间线，不改数据
    "auditor": ["read_chapter", "read_bible", "check_foreshadow", "check_timeline"],
    # 规划师：读写大纲，读设定/参考资料
    "planner": ["read_bible", "read_outline", "write_outline", "read_references"],
    # 世界引擎：只读世界设定/大纲/世界状态
    "world_engine": ["read_world_settings", "read_outline", "read_world_state"],
    # 后验裁决：只读章节/设定/世界状态/伏笔
    "post_hoc": ["read_chapter", "read_bible", "read_world_state", "read_foreshadows"],
    # 管理员：全部工具
    "admin": ["*"],
}

# 角色工具黑名单（可选，优先级高于白名单）
# 格式与 TOOL_WHITELIST 一致，列出的工具即使白名单允许也会被拒绝
TOOL_BLACKLIST: dict[str, list[str]] = {}


def is_tool_allowed(role: str, tool_name: str) -> bool:
    """检查指定角色是否允许使用某个工具。

    借鉴 DeterminFlow tool_guard.py 的 GuardResult.check 逻辑：
    - 黑名单优先：在黑名单中则拒绝
    - admin 角色或白名单含 "*" 时直接放行
    - 白名单校验：不在白名单中则拒绝
    - 未知角色默认拒绝（最小权限原则）

    Args:
        role: Agent 角色名（如 writer/auditor/planner 等）
        tool_name: 工具名称

    Returns:
        True 表示允许使用，False 表示拒绝
    """
    # 黑名单优先检查
    if tool_name in TOOL_BLACKLIST.get(role, []):
        logger.warning("工具 %s 被角色 %s 黑名单拒绝", tool_name, role)
        return False

    whitelist = TOOL_WHITELIST.get(role)
    if whitelist is None:
        # 未知角色：最小权限原则，默认拒绝
        logger.warning("未知角色 %s，拒绝工具 %s（最小权限原则）", role, tool_name)
        return False

    # 通配符放行（admin 等全权限角色）
    if "*" in whitelist:
        return True

    if tool_name in whitelist:
        return True

    logger.warning("工具 %s 不在角色 %s 的白名单中", tool_name, role)
    return False


def filter_tools_for_role(role: str, all_tools: dict) -> dict:
    """根据角色权限过滤工具字典，只返回允许的工具。

    借鉴 DeterminFlow tool_guard.py 的 make_guarded_wrapper 思路：
    在工具注册阶段就过滤，不暴露给 LLM 的工具不会被调用。

    Args:
        role: Agent 角色名
        all_tools: 全部工具集合，支持两种格式：
                   - dict[str, dict]：工具名 -> 工具定义
                   - list[dict]：OpenAI function calling 格式的列表

    Returns:
        过滤后的工具字典 {工具名: 工具定义}
    """
    # 兼容 list 输入（OpenAI function calling 格式的 TOOLS_SCHEMA）
    if isinstance(all_tools, list):
        all_tools = {
            t["function"]["name"]: t for t in all_tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
            and t["function"].get("name")
        }

    filtered: dict[str, Any] = {}
    for name, definition in all_tools.items():
        if is_tool_allowed(role, name):
            filtered[name] = definition

    logger.info("角色 %s 工具过滤完成：%d/%d 个工具可用",
                role, len(filtered), len(all_tools))
    return filtered
