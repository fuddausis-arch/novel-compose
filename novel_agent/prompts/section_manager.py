"""Prompt Section 化管理系统。

借鉴 bishu-novel prompts.json 的设计：
- 每个 Agent 的 Prompt 拆成多个 section（role/rules/output/constraints 等）
- 每个 section 有 enabled 字段，可以开关
- 支持 token 估算（粗略按字符数/4 估算）
- 支持模板变量替换 {{variable}}
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 默认配置文件路径（与本文件同目录的 sections.json）
_DEFAULT_SECTIONS_PATH = Path(__file__).parent / "sections.json"

# 模板变量正则：匹配 {{variable_name}}
_TEMPLATE_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class PromptSection:
    """单个 Prompt section 定义。

    Attributes:
        name: section 名称（如 role / rules / output_format）
        content: section 内容，支持 {{variable}} 模板变量
        enabled: 是否启用（False 时不拼入最终 prompt）
        order: 拼接顺序，数值越小越靠前
    """
    name: str
    content: str
    enabled: bool = True
    order: int = 0


class PromptManager:
    """Prompt Section 管理器。

    从 JSON 文件加载各 Agent 的 section 定义，支持：
    - 按 agent_type 构建 prompt（拼接 enabled 的 section，替换模板变量）
    - 粗略 token 估算
    - section 开关
    - 热重载（修改 JSON 后重新加载）
    """

    def __init__(self, config_path: str | Path | None = None):
        """初始化 PromptManager。

        Args:
            config_path: sections.json 路径，None 时使用默认路径
        """
        self._config_path = Path(config_path) if config_path else _DEFAULT_SECTIONS_PATH
        # _sections: dict[agent_type, list[PromptSection]]，按 order 排序
        self._sections: dict[str, list[PromptSection]] = {}
        self.load_from_json(self._config_path)

    def load_from_json(self, path: str | Path) -> None:
        """从 JSON 文件加载 section 定义（支持热重载）。

        JSON 格式：
        {
            "agents": {
                "writer": {
                    "sections": [
                        {"name": "role", "content": "...", "enabled": true, "order": 0}
                    ]
                }
            }
        }

        重复调用即可实现热重载：修改 JSON 后重新 load_from_json 即可刷新内存中的 section。
        """
        path = Path(path)
        if not path.exists():
            logger.warning("PromptManager: 配置文件不存在: %s", path)
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("PromptManager: 加载配置文件失败: %s", e)
            return

        self._sections.clear()
        agents = data.get("agents", {})
        for agent_type, agent_def in agents.items():
            sections = []
            for sec in agent_def.get("sections", []):
                sections.append(PromptSection(
                    name=sec.get("name", ""),
                    content=sec.get("content", ""),
                    enabled=sec.get("enabled", True),
                    order=sec.get("order", 0),
                ))
            # 按 order 排序，保证拼接顺序正确
            sections.sort(key=lambda s: s.order)
            self._sections[agent_type] = sections

        logger.info("PromptManager: 已加载 %d 个 agent 的 section 配置", len(self._sections))

    def reload(self) -> None:
        """热重载：重新从配置文件加载（修改 JSON 后调用）。"""
        self.load_from_json(self._config_path)

    def get_sections(self, agent_type: str) -> list[PromptSection]:
        """获取某 agent 的所有 section（按 order 排序）。

        返回的是内部列表的副本，修改不会影响管理器状态。
        """
        return list(self._sections.get(agent_type, []))

    def build_prompt(self, agent_type: str, variables: dict | None = None) -> str:
        """拼接 enabled 的 section，替换模板变量，返回完整 prompt。

        Args:
            agent_type: agent 类型（如 writer / auditor）
            variables: 模板变量字典，替换 content 中的 {{variable}}

        Returns:
            拼接后的完整 prompt 字符串；无 section 定义时返回空字符串
        """
        sections = self._sections.get(agent_type, [])
        if not sections:
            logger.warning("PromptManager: agent_type '%s' 无 section 定义", agent_type)
            return ""

        variables = variables or {}
        parts = []
        for sec in sections:
            if not sec.enabled:
                continue
            # 替换模板变量（未提供的变量保留原样，便于分阶段填充）
            content = self._render_template(sec.content, variables)
            parts.append(content)

        return "\n\n".join(parts)

    def _render_template(self, content: str, variables: dict) -> str:
        """替换 content 中的 {{variable}} 模板变量。

        未提供值的变量保留原样（不报错），便于分阶段填充。
        """
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            return str(variables.get(key, match.group(0)))

        return _TEMPLATE_VAR_RE.sub(_replace, content)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略 token 估算。

        中文按字符数 / 2，英文按单词数 * 1.3，数字按字符数 * 0.25，取整相加。
        """
        # 中文字符数（CJK 统一表意文字区）
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        # 英文单词数（连续字母序列视为一个单词）
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        # 数字字符数
        digit_chars = len(re.findall(r'[0-9]', text))

        tokens = chinese_chars / 2 + english_words * 1.3 + digit_chars * 0.25
        return int(tokens)

    def toggle_section(self, agent_type: str, section_name: str, enabled: bool) -> bool:
        """开关某个 section。

        Args:
            agent_type: agent 类型
            section_name: section 名称
            enabled: True 启用 / False 禁用

        Returns:
            True 表示成功找到并切换，False 表示未找到该 section
        """
        sections = self._sections.get(agent_type, [])
        for sec in sections:
            if sec.name == section_name:
                sec.enabled = enabled
                return True
        logger.warning("PromptManager: 未找到 agent '%s' 的 section '%s'", agent_type, section_name)
        return False
