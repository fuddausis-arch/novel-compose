"""Prompt Section 化管理系统。

借鉴 bishu-novel prompts.json 的设计，将每个 Agent 的 Prompt 拆成
多个可独立开关的 section，支持模板变量替换和 token 估算。
"""
from novel_agent.prompts.section_manager import PromptManager, PromptSection

__all__ = ["PromptManager", "PromptSection"]
