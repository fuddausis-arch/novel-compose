"""蒸馏模块：从优质作品中提取写作风格，生成可复用的 Skill。"""
from novel_agent.distillation.store import DistillationStore
from novel_agent.distillation.engine import DistillationEngine

__all__ = ["DistillationStore", "DistillationEngine"]
