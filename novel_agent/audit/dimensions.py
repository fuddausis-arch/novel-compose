"""审计维度定义：融合 spec 15维 + knowrite Fitness 五维 + Acid Test 四维。

spec 第 5 节。关键维度任一不过 → 直接打回重写；次要维度通过率 ≥80% → 通过。
Fitness 总分 = 字数/重复率/审阅通过率/读者分/大纲偏离 加权。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AuditCategory(str, Enum):
    CONSISTENCY = "一致性"
    CHARACTER = "人物"
    PLOT = "情节"
    STYLE = "文风"
    PHYSICAL = "物理"
    ENVIRONMENT = "环境"
    RELATIONSHIP = "关系"


@dataclass(frozen=True)
class Dimension:
    name: str
    category: AuditCategory
    check: str           # 检查内容描述
    description: str = ""
    critical: bool = False   # True=任一不过直接打回


# spec 15维 + Fitness + Acid Test 融合
DIMENSIONS: list[Dimension] = [
    # 一致性（spec 15维 + knowrite）
    Dimension("设定一致性", AuditCategory.CONSISTENCY, "对照圣经检查设定不崩", critical=True),
    Dimension("伏笔准确性", AuditCategory.CONSISTENCY, "伏笔生命周期验证（埋设/发展/回收）", critical=True),
    Dimension("时间线连贯", AuditCategory.CONSISTENCY, "时间跨度合理性"),
    Dimension("地理正确性", AuditCategory.CONSISTENCY, "地点移动逻辑"),
    Dimension("信息边界", AuditCategory.CONSISTENCY, "角色只说知道的信息（交互矩阵验证）", critical=True),
    Dimension("资源合理性", AuditCategory.CONSISTENCY, "物品消耗/获取/衰减逻辑"),
    # 人物（spec 15维 + Acid Test 心理维）
    Dimension("情感连续性", AuditCategory.CHARACTER, "情感弧线一致性"),
    Dimension("人物OOC", AuditCategory.CHARACTER, "MAR 法则对照，行为符合人设", critical=True),
    Dimension("对话真实性", AuditCategory.CHARACTER, "对话符合角色身份"),
    Dimension("视角一致性", AuditCategory.CHARACTER, "第三人称限制视角"),
    # 情节（spec 15维 + Fitness）
    Dimension("支线推进度", AuditCategory.PLOT, "支线进度板更新"),
    Dimension("节奏控制", AuditCategory.PLOT, "每 300-500 字一个转折"),
    Dimension("爽点分布", AuditCategory.PLOT, "高潮间隔合理性"),
    Dimension("读者期待管理", AuditCategory.PLOT, "章末钩子强度"),
    Dimension("大纲偏离度", AuditCategory.PLOT, "是否偏离本章大纲"),
    # 文风（spec 15维 + 反AI味六维度）
    Dimension("文风统一", AuditCategory.STYLE, "文风指纹一致性"),
    Dimension("AI标记词检测", AuditCategory.STYLE, "禁止句式/转折词限频"),
    Dimension("反AI味-句式工整度", AuditCategory.STYLE, "句子长度是否过于均匀？高潮段应有3-7字超短句"),
    Dimension("反AI味-修辞均匀度", AuditCategory.STYLE, "比喻/形容词是否全程一致？战斗密集过渡段应零修辞"),
    Dimension("反AI味-情感正确度", AuditCategory.STYLE, "角色情感是否过于合理？应有反直觉反应"),
    Dimension("反AI味-过渡平滑度", AuditCategory.STYLE, "场景切换是否太多过渡词？应硬切场景"),
    Dimension("反AI味-描写全面度", AuditCategory.STYLE, "每段是否感官齐全？应只保留1-2种感官"),
    Dimension("反AI味-对话功能化", AuditCategory.STYLE, "所有对话是否都在推动剧情？应有10-20%废话闲聊"),
    # 物理（Acid Test 物理维）
    Dimension("物理一致性", AuditCategory.PHYSICAL, "身体/伤/年龄/生死（死后不能行动）", critical=True),
    # 环境（Acid Test 环境维）
    Dimension("环境一致性", AuditCategory.ENVIRONMENT, "符合地点时代+lore"),
    # 关系（Acid Test 化学维）
    Dimension("关系铺垫", AuditCategory.RELATIONSHIP, "关系变化有铺垫不突兀"),
]

CRITICAL_DIMENSIONS = [d for d in DIMENSIONS if d.critical]
