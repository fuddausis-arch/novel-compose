"""写作助手 Skill：Main Agent 双重角色。

借鉴 bishu-novel writing-assistant Skill：
- 角色 1：写作助手 -- 对话式创作（设定/大纲/章节交互）
- 角色 2：工作流主管 -- 调度 7 条工作流（build/character/story-plan/outline/mvp/polish/post-hoc）

提供工作流选择决策树和用户意图解析，供 ChatAgent 调用。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── 双重角色系统提示词 ────────────────────────────────────────
WRITING_ASSISTANT_PROMPT = """你是一个网文写作助手，拥有双重角色：

【角色 1：写作助手】
在对话式创作模式下，你直接与用户交互，帮助：
- 建立和修改设定（角色/世界观/势力/伏笔）
- 创建和调整大纲
- 交互式写章节正文
- 回答关于项目设定的问题
- 执行用户的修改指令

【角色 2：工作流主管】
当用户需要系统化生成时，你作为工作流主管，调度以下 7 条工作流：

1. **build** -- 建书工作流：创建项目 + 初始化世界观 + 生成题材模板
2. **character** -- 角色工作流：批量创建角色 + 建立关系网 + 生成角色弧光
3. **story-plan** -- 故事规划工作流：生成卷/arc/章纲的分层大纲
4. **outline** -- 大纲工作流：生成详细章纲（爽点/伏笔/角色约束）
5. **mvp** -- 正文生成工作流：写正文 + 审计 + 润色 + 摘要 + 后验裁决
6. **polish** -- 润色工作流：对已有正文做深度去 AI 味 + 风格模仿
7. **post-hoc** -- 后验裁决工作流：对已保存章节做事后一致性检查

【工作流选择原则】
- 用户说"建一本XX小说" -> build 工作流
- 用户说"创建角色/设定角色" -> character 工作流
- 用户说"做大纲/规划故事" -> story-plan 工作流
- 用户说"写下一章/生成正文" -> mvp 工作流（需先有大纲）
- 用户说"润色/优化已有章节" -> polish 工作流
- 用户说"检查一致性/后验" -> post-hoc 工作流
- 没有明确工作流意图时，进入角色 1 的对话式创作

【章节循环顺序】
连续写多章时，每章的执行顺序：
mvp -> polish(可选) -> post-hoc -> 下一章

【前置条件检查】
- mvp 工作流要求至少有 1 条章纲，否则提示用户先创建大纲
- polish 工作流要求至少有 1 章已生成正文
- post-hoc 工作流要求至少有 1 章已保存摘要
"""

# ── 章节循环顺序 ──────────────────────────────────────────────
CHAPTER_LOOP_ORDER: list[str] = ["mvp", "polish", "post-hoc"]

# 7 条工作流名称
WORKFLOW_NAMES: list[str] = [
    "build", "character", "story-plan", "outline",
    "mvp", "polish", "post-hoc",
]


def select_workflow(project_state: dict[str, Any]) -> str:
    """工作流选择决策树。

    根据项目当前状态自动推荐下一步工作流。

    Args:
        project_state: 项目状态 dict，可包含以下字段：
            - has_project: bool -- 是否已建项目
            - has_world: bool -- 是否有世界观设定
            - has_characters: bool -- 是否有角色
            - has_outlines: bool -- 是否有章纲
            - has_chapters: bool -- 是否有已生成章节
            - has_summaries: bool -- 是否有章节摘要
            - user_intent: str -- 用户意图关键词

    Returns:
        推荐的工作流名称
    """
    has_project = project_state.get("has_project", False)
    if not has_project:
        return "build"

    has_world = project_state.get("has_world", False)
    if not has_world:
        return "build"

    has_characters = project_state.get("has_characters", False)
    if not has_characters:
        return "character"

    has_outlines = project_state.get("has_outlines", False)
    if not has_outlines:
        return "story-plan"

    has_chapters = project_state.get("has_chapters", False)
    has_summaries = project_state.get("has_summaries", False)

    # 有章节但没摘要 -> 需要 post-hoc
    if has_chapters and not has_summaries:
        return "post-hoc"

    # 有章纲但没章节 -> 需要写正文
    if not has_chapters:
        return "mvp"

    # 一切就绪，默认推荐继续写下一章
    return "mvp"


def parse_user_intent(message: str) -> dict[str, Any]:
    """解析用户意图（创作/查询/修改）。

    Args:
        message: 用户消息文本

    Returns:
        {
            "intent": "create" | "query" | "modify" | "workflow" | "chat",
            "workflow": str | None,  -- 匹配到的工作流名
            "target": str,           -- 操作目标（角色/大纲/章节等）
            "confidence": float,     -- 置信度 0-1
        }
    """
    msg = message.strip().lower()

    # 强创作指令优先：用户显式说"写第X章/写下一章"时，
    # 即使消息中提到"故事规划/大纲"等上下文词，也以创作指令为主意图。
    # （前置检查由 select_workflow 负责，会依据状态回到 story-plan。）
    _STRONG_CREATE_KEYWORDS = ["写第", "写下一章", "生成下一章", "创作第", "生成正文"]
    if any(kw in msg for kw in _STRONG_CREATE_KEYWORDS):
        return {
            "intent": "workflow",
            "workflow": "mvp",
            "target": "chapter",
            "confidence": 0.95,
        }

    # 工作流意图匹配
    workflow_keywords: dict[str, list[str]] = {
        "build": ["建书", "建一本", "新建小说", "创建项目", "新项目"],
        "character": ["创建角色", "设定角色", "新增角色", "角色设计"],
        "story-plan": ["做大纲", "规划故事", "故事规划", "生成大纲", "规划大纲"],
        "outline": ["章纲", "详细大纲", "细纲"],
        "mvp": ["写下一章", "写正文", "生成正文", "写第", "继续写", "生成下一章"],
        "polish": ["润色", "优化正文", "去ai味", "改写润色"],
        "post-hoc": ["后验", "一致性检查", "检查一致", "事后检查"],
    }

    for workflow, keywords in workflow_keywords.items():
        for kw in keywords:
            if kw in msg:
                return {
                    "intent": "workflow",
                    "workflow": workflow,
                    "target": _infer_target(msg, workflow),
                    "confidence": 0.9,
                }

    # 查询意图
    query_keywords = ["查询", "查看", "看一下", "有什么", "列表", "搜", "搜索", "状态"]
    if any(kw in msg for kw in query_keywords):
        return {
            "intent": "query",
            "workflow": None,
            "target": _infer_target(msg, ""),
            "confidence": 0.7,
        }

    # 修改意图
    modify_keywords = ["修改", "改", "更新", "删除", "调整", "重写"]
    if any(kw in msg for kw in modify_keywords):
        return {
            "intent": "modify",
            "workflow": None,
            "target": _infer_target(msg, ""),
            "confidence": 0.7,
        }

    # 创建意图（非工作流的创建操作）
    create_keywords = ["创建", "新增", "添加", "建"]
    if any(kw in msg for kw in create_keywords):
        return {
            "intent": "create",
            "workflow": None,
            "target": _infer_target(msg, ""),
            "confidence": 0.6,
        }

    # 默认：普通聊天
    return {
        "intent": "chat",
        "workflow": None,
        "target": "",
        "confidence": 0.3,
    }


def _infer_target(message: str, workflow: str) -> str:
    """从消息中推断操作目标。"""
    targets_map: list[tuple[str, str]] = [
        ("角色", "character"),
        ("人物", "character"),
        ("大纲", "outline"),
        ("章纲", "outline"),
        ("伏笔", "foreshadow"),
        ("世界观", "world"),
        ("势力", "faction"),
        ("章节", "chapter"),
        ("正文", "chapter"),
    ]
    for keyword, target in targets_map:
        if keyword in message:
            return target
    # 根据工作流推断默认目标
    if workflow in ("build", "character"):
        return "character"
    if workflow in ("story-plan", "outline"):
        return "outline"
    if workflow in ("mvp", "polish", "post-hoc"):
        return "chapter"
    return ""
