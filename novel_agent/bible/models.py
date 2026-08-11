"""圣经 ORM 模型：9 库 + 事件流表。

对应 spec 第 2.2 节。所有时间戳用 UTC。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    """小说项目元信息。"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    genre = Column(String(100), default="")
    summary = Column(Text, default="")
    style = Column(Text, default="")
    constitution = Column(Text, default="")
    target_audience = Column(String(200), default="")
    central_concept = Column(Text, default="")  # JSON: {"core_hook":"","protagonist_goal":"","taboos":[]}
    word_count_target = Column(Integer, default=0)
    target_volumes = Column(Integer, default=0)   # 全书目标卷数（0=未设定，由 AI 自决）
    golden_finger = Column(Text, default="")      # JSON: 金手指设定 {name,type,core_ability,limitation,growth,origin}
    protagonist = Column(Text, default="")        # JSON: 主角设定 {name,identity,core_contradiction,sensory_memories,absolute_taboos,motivation,initial_state}
    generation_checkpoint = Column(JSON, default=dict)  # 元认知 checkpoint：失败章节、已完成、待生成范围
    style_books = Column(JSON, default=list)  # 参考书单：已蒸馏作品 id 列表（distill_works.id），注入蒸馏 skill 时按书过滤
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Character(Base):
    """角色卡（对应「主要人物卡」）。"""
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_character_project_name"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), default="")          # 主角/配角/反派
    age = Column(String(50), default="")
    gender = Column(String(20), default="")
    appearance = Column(Text, default="")
    background = Column(Text, default="")
    personality = Column(Text, default="")
    motivation = Column(Text, default="")
    # 活人味三件套（替代形容词列表）
    core_contradiction = Column(Text, default="")    # 承重矛盾："他是___的人，但同时___"
    sensory_memories = Column(Text, default="")      # 感官瞬间：3-4个第一人称关键记忆片段
    absolute_taboos = Column(Text, default="")       # 绝对禁令：2-3条"这个角色绝对不会做X"
    importance = Column(String(50), default="")    # 主角/配角/关键人物/小人物/NPC
    # 动态状态（每章 diff 更新）
    current_location = Column(String(200), default="")
    current_emotion = Column(String(100), default="")
    known_info = Column(Text, default="")          # 角色已知信息（信息边界）
    arc = Column(Text, default="")
    relationships = Column(Text, default="")
    secrets = Column(Text, default="")
    # 扩展设定字段
    language_style = Column(Text, default="")       # 语言风格+经典台词示例
    combat_style = Column(Text, default="")          # 战斗风格+战术体系
    growth_curve = Column(Text, default="")          # 成长曲线（阶段/能力/心理变化）
    emotional_anchor = Column(Text, default="")      # 情感锚点（人物/事物/信念）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Faction(Base):
    __tablename__ = "factions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    alias = Column(String, default="")
    type = Column(String, default="")
    tier = Column(String(50), default="")           # 顶级势力/一流势力/二流势力/三流势力/隐世势力
    alignment = Column(String, default="")
    description = Column(Text, default="")
    history = Column(Text, default="")
    goals = Column(Text, default="")
    hierarchy = Column(Text, default="")
    territories = Column(Text, default="")
    resources = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_faction_name"),)


class FactionRelationship(Base):
    __tablename__ = "faction_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_faction_id = Column(Integer, ForeignKey("factions.id", ondelete="CASCADE"), nullable=False)
    target_faction_id = Column(Integer, ForeignKey("factions.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String, default="neutral")
    strength = Column(Integer, default=0)
    description = Column(Text, default="")
    since_chapter = Column(Integer, default=0)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_character = Column(String, nullable=False, index=True)
    target_character = Column(String, nullable=False, index=True)
    relation_type = Column(String, default="other")
    relation_subtype = Column(String, default="")
    strength = Column(Integer, default=0)
    description = Column(Text, default="")
    since_chapter = Column(Integer, default=0)
    status = Column(String, default="active")
    is_bidirectional = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "source_character", "target_character", "relation_type", name="uix_project_char_rel"),)


class Monster(Base):
    __tablename__ = "monsters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    alias = Column(String, default="")
    species = Column(String, default="")
    rank = Column(String, default="")
    tier = Column(String(50), default="")           # BOSS/精英/首领/小怪/普通
    attributes = Column(Text, default="")
    skills = Column(Text, default="")
    drops = Column(Text, default="")
    habitats = Column(Text, default="")
    behavior = Column(Text, default="")
    weaknesses = Column(Text, default="")
    lore = Column(Text, default="")
    first_appearance = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_monster_name"),)


class Instance(Base):
    """副本/关卡/特殊场景（通用，不限项目类型）。"""
    __tablename__ = "instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)        # 副本名称
    instance_type = Column(String(50), default="")     # 类型：文明副本/量子隧穿/迷宫/试炼/其他
    related_volume = Column(Integer, default=0)        # 所属卷号
    chapter_range = Column(String(50), default="")     # 章节范围，如"86-100"
    objective = Column(Text, default="")               # 副本目的/目标
    mechanism = Column(Text, default="")               # 副本机制/规则
    tone = Column(String(50), default="")              # 调性：悲壮/轻松/紧张/悬疑
    difficulty = Column(String(50), default="")        # 难度类型：数值/机制/混合
    rewards = Column(Text, default="")                 # 奖励/获得物
    cost = Column(Text, default="")                    # 代价/消耗
    description = Column(Text, default="")             # 详细描述
    order = Column(Integer, default=0)                 # 排序
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_instance_name"),)


class EntityAppearance(Base):
    __tablename__ = "entity_appearances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String, nullable=False)  # character / faction / monster
    entity_id = Column(String, nullable=False)    # name for character, id for faction/monster (store as string)
    chapter = Column(Integer, nullable=False, index=True)
    role_in_chapter = Column(String, default="mention")  # lead / participant / mention / background
    context_snippet = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "entity_type", "entity_id", "chapter", name="uix_entity_appearance"),)


class WorldSetting(Base):
    """世界设定（对应「核心设定」）。"""
    __tablename__ = "world_settings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), default="")      # 世界观/力量体系/势力/地点/规则
    dimension = Column(String(50), default="")     # 六维度：core_rules/spacetime/society/history/existence/information
    title = Column(String(200), default="")
    content = Column(Text, default="")
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Outline(Base):
    """大纲：卷→弧→章三级（对应「细纲」）。"""
    __tablename__ = "outlines"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(20), nullable=False, index=True)     # volume / arc / chapter
    parent_id = Column(Integer, ForeignKey("outlines.id", ondelete="CASCADE"), nullable=True, index=True)
    order = Column(Integer, default=0)
    act = Column(String(50), default="")           # 开端/发展/高潮/结局 或 卷名
    strand = Column(String(20), default="")        # quest / fire / constellation
    title = Column(String(200), default="")
    summary = Column(Text, default="")
    # 约束载荷（大纲带规范，正文满足规范，summarize校验而非抽取）
    required_beats = Column(Text, default="")      # JSON: [{"tier":"small","type":"打脸","intensity":5}]
    owed_debts = Column(Text, default="")          # JSON: [{"type":"复仇","desc":"...","pressure":3}]
    required_hooks = Column(Text, default="")      # JSON: {"type":"悬念","target_strength":7}
    character_constraints = Column(Text, default="")  # JSON: {"陆辰":{"location":"基地","emotion":"愤怒"}}
    phase = Column(String(20), default="regular")  # opening/shangjia/regular（黄金三章/上架/常规）
    # LLM 结构化输出落库（B1/B3：卷纲 key_events、细纲 key_characters/emotional_arc 不再丢弃）
    key_events = Column(Text, default="")            # JSON: [{"title":"...","description":"...","chapter":1}]
    key_characters = Column(Text, default="")        # JSON: [{"name":"...","role":"...","arc":"..."}]
    emotional_arc = Column(Text, default="")         # JSON: [{"chapter":1,"emotion":"...","trigger":"..."}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "level", "parent_id", "order", name="uix_outline_project_level_parent_order"),)


class Foreshadow(Base):
    """伏笔台账（对应「伏笔与道具追踪」）。"""
    __tablename__ = "foreshadows"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)  # S-001 / M-001 / L-001
    tier = Column(String(10), default="")          # short / medium / long
    plant_chapter = Column(Integer, default=0, index=True)
    description = Column(Text, default="")
    depends_on = Column(Text, default="")          # 依赖的其他伏笔 id
    status = Column(String(20), default="pending", index=True)  # pending/planted/developing/resolved/abandoned
    planned_resolve_chapter = Column(Integer, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ForeshadowImplant(Base):
    """伏笔植入方案（对应「核心伏笔早期植入方案」）。"""
    __tablename__ = "foreshadow_implants"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)
    chapter = Column(Integer, default=0)
    implant_method = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterSummary(Base):
    """章节摘要历史。"""
    __tablename__ = "chapter_summaries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    title = Column(String(200), default="")
    time_location = Column(String(500), default="")
    core_events = Column(Text, default="")
    characters_present = Column(Text, default="")
    emotion_changes = Column(Text, default="")
    foreshadow_dynamics = Column(Text, default="")
    subplot_progress = Column(Text, default="")
    chapter_hook = Column(Text, default="")
    word_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmotionArc(Base):
    """情感弧线追踪。"""
    __tablename__ = "emotion_arcs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    character_name = Column(String(100), nullable=False, index=True)
    chapter = Column(Integer, nullable=False)
    event = Column(Text, default="")
    emotion_before = Column(String(100), default="")
    emotion_after = Column(String(100), default="")
    growth = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SubplotBoard(Base):
    """支线进度板。"""
    __tablename__ = "subplot_board"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    is_main = Column(Integer, default=0)           # 1=主线 0=支线
    status = Column(String(50), default="active")  # active/paused/resolved
    progress = Column(Integer, default=0)          # 0-100
    related_characters = Column(Text, default="")
    next_goal = Column(Text, default="")
    planned_resolve_chapter = Column(Integer, default=0)
    updated_chapter = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CharacterMatrix(Base):
    """角色交互矩阵：相遇记录/知识边界/信息传播。"""
    __tablename__ = "character_matrix"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False)
    character_a = Column(String(100), nullable=False)
    character_b = Column(String(100), default="")
    interaction_type = Column(String(50), default="")  # meeting/conflict/cooperation/info_share
    info_exchanged = Column(Text, default="")
    relationship_change = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class TruthEvent(Base):
    """事件流：不可变追加，支持 time-travel 查询（spec 2.3）。"""
    __tablename__ = "truth_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    type = Column(String(50), nullable=False)      # foreshadow_planted/foreshadow_resolved/
                                                   # character_state_change/resource_change/
                                                   # relationship_change/timeline_event
    entity_id = Column(String(100), default="")    # 伏笔id/角色名/物品名
    payload = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class StateChange(Base):
    """实体状态增量：记录角色/物品/势力等字段变化。"""
    __tablename__ = "state_changes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    entity_type = Column(String(50), default="")   # 角色/地点/物品/势力/招式
    entity_id = Column(String(100), default="", index=True)
    field = Column(String(100), default="")        # 字段路径，如 realm / location.current
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryRefinement(Base):
    """设定提炼日志（白盒溯源）：记录"哪一章/哪个提炼器把什么信息写回了设定库"。

    来源溯源：角色卡/世界观/故事线的每次自动更新都留一条记录，
    前端可按实体查看"这条设定是哪章定的"，设定冲突时可下钻原文。
    """
    __tablename__ = "memory_refinements"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)     # 来源章节
    entity_type = Column(String(50), default="")              # character / worldsetting / storyline / plot_debt
    entity_id = Column(String(200), default="", index=True)   # 角色名 / 设定标题 / 线名
    field = Column(String(100), default="")                   # 更新的字段，如 notes / location / summary
    new_value = Column(Text, default="")
    source_preview = Column(Text, default="")                 # 正文/摘要中对应的原句（溯源用）
    method = Column(String(50), default="refine")             # refine=提炼器自动 / manual=人工
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterCommit(Base):
    """章节提交记录：标记本章已提取事实并落库。"""
    __tablename__ = "chapter_commits"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    status = Column(String(20), default="draft")   # 章节提交状态（非任务状态，不入 state_common）："draft" 草稿 / "committed" 已提交
    summary = Column(Text, default="")
    word_count = Column(Integer, default=0)
    committed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RelationshipChange(Base):
    """人物/势力关系变化：记录关系字段的旧值→新值，支持不可变追溯。"""
    __tablename__ = "relationship_changes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    entity_type = Column(String(50), default="")   # character / faction
    source_id = Column(String(100), default="")
    target_id = Column(String(100), default="")
    field = Column(String(100), default="")        # 字段路径，如 relation_type / strength / description
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class AiSuggestion(Base):
    """AI 一键串联建议历史。"""
    __tablename__ = "ai_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    context_type = Column(String(50), nullable=False)   # outline / chapter / monster / faction / relationship
    context_id = Column(String(100), default="")        # outline.id / chapter number / asset id
    suggest_type = Column(String(50), nullable=False)   # plot / monster / faction / relationship
    prompt = Column(Text, default="")
    raw_response = Column(Text, default="")
    adopted_items = Column(JSON, default=list)
    status = Column(String(20), default="adopted")      # adopted / partial / rejected
    created_at = Column(DateTime, default=datetime.utcnow)


class StateSnapshot(Base):
    """状态快照：O(1) 读当前世界状态，防止长篇上下文爆炸。

    每章生成后存一条快照，包含角色状态/伏笔状态/支线进度/势力状态的序列化 JSON。
    CoreMemoryAssembler 优先读快照而非全量查表。
    """
    __tablename__ = "state_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    snapshot_data = Column(JSON, default=dict)  # 序列化的世界状态
    drift_score = Column(Integer, default=0)    # 保真度校验漂移分数
    is_full_resummary = Column(Boolean, default=False)  # 是否全量重摘要
    created_at = Column(DateTime, default=datetime.utcnow)


class PleasureBeat(Base):
    """爽点供应链：档位规划/断层检测/交付追踪。"""
    __tablename__ = "pleasure_beats"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    tier = Column(String(20), default="small")      # small/medium/large
    beat_type = Column(String(50), default="")       # 打脸/揭示/获取/共鸣/碾压/守护
    intensity = Column(Integer, default=0)           # 1-10
    phase = Column(String(20), default="regular")    # opening/shangjia/regular
    delivered = Column(Boolean, default=False)       # 是否已交付
    delivered_intensity = Column(Integer, default=0) # 实际交付强度
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlotDebt(Base):
    """欠账账本：追踪未兑现的剧情承诺。"""
    __tablename__ = "plot_debts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    debt_type = Column(String(50), default="")        # 复仇/承诺/秘密/因果
    description = Column(Text, default="")
    pressure = Column(Integer, default=3)             # 1-5，5=最高压（基础压力）
    term = Column(String(20), default="short")        # short=短线（本卷内）/ long=长线（跨卷）
    status = Column(String(20), default="open")       # open/resolved/abandoned
    created_chapter = Column(Integer, default=0)      # 欠账产生章节
    resolved_chapter = Column(Integer, default=0)     # 欠账偿还章节
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatSession(Base):
    """聊天会话：按对象隔离或项目级全局会话。"""
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    session_type = Column(String(20), nullable=False)      # "object" | "global"
    object_type = Column(String(50), default="")           # chapter|outline|character|monster|world|faction|relationship
    object_id = Column(String(100), default="")
    title = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    """聊天消息。"""
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)              # "user" | "assistant" | "system"
    content = Column(Text, default="")
    actions = Column(JSON, default=list)                   # 主 Agent 执行的动作列表
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterFeedback(Base):
    """用户对章节的聊天反馈，待生成时注入 writer prompt。"""
    __tablename__ = "chapter_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    feedback = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    applied = Column(Boolean, default=False)


class RedLine(Base):
    """红线：套壳改写时的绝对约束，AI不可违反。"""
    __tablename__ = "red_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    scope = Column(String(20), default="project")          # "project" | "chapter"
    chapter_num = Column(Integer, nullable=True, index=True)  # NULL=项目级，有值=章级
    content = Column(Text, nullable=False)                  # 红线内容
    severity = Column(String(10), default="hard")           # "hard"=绝对不可违反 | "soft"=尽量遵守
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Gag(Base):
    """梗：笑点/包袱/桥段/套路/彩蛋，写作时注入。"""
    __tablename__ = "gags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), default="")                  # 梗名称
    description = Column(Text, default="")                  # 梗描述/用法说明
    category = Column(String(20), default="笑点")           # "笑点" | "桥段" | "彩蛋"
    status = Column(String(20), default="待用")             # 历史中文枚举（"待用" | "使用中" | "已用"），保持存量兼容，勿改
    first_chapter = Column(Integer, nullable=True)          # 首次出现章节
    usage_notes = Column(Text, default="")                  # 使用备注
    created_at = Column(DateTime, default=datetime.utcnow)


class EntityNameOverride(Base):
    """命名权威：用户手动合并的别名记录（"我的修正"列表，可回滚）。

    canonical_name 为规范名（Bible 实体名），alias 为被合并进来的别名/称呼。
    删除记录即回滚合并。实体卡片抽屉据此把别名归并到规范名下展示。
    """
    __tablename__ = "entity_name_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(20), nullable=False, index=True)  # character/faction/monster/location
    canonical_name = Column(String(200), nullable=False)          # 规范名（Bible 实体名）
    alias = Column(String(200), nullable=False)                   # 被合并的别名/称呼
    note = Column(String(500), default="")                        # 备注（可选）
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "canonical_name", "alias", name="uq_entity_name_override"),
    )


class ImportedChapter(Base):
    """导入的章节大纲（来自文件夹导入，用于套壳改写）。"""
    __tablename__ = "imported_chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_filename = Column(String(500), default="")       # 原始文件名
    chapter_order = Column(Integer, default=0)              # 章节序号
    title = Column(String(200), default="")                 # 章节标题
    meta_info = Column(Text, default="")                    # 元信息（人物/系统/道具/地点）
    chapter_outline = Column(Text, default="")              # 章纲概要
    detail_outline = Column(Text, default="")              # 细纲节拍
    pleasure_hooks = Column(Text, default="")               # 爽点/钩子
    shell_annotation = Column(Text, default="")             # 套壳标注（皮/骨）
    raw_content = Column(Text, default="")                  # 原始完整内容
    created_at = Column(DateTime, default=datetime.utcnow)


class WorldState(Base):
    """世界状态快照：每章 world_engine 节点产出的世界暗流状态。

    借鉴 bishu-novel world_state.json，存储势力动态和暗线运行。
    """
    __tablename__ = "world_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)          # 产生该状态的章节号
    world_time = Column(String(200), default="")                   # 当前世界时间描述
    time_advanced_days = Column(Integer, default=0)                 # 时间推进天数
    forces = Column(JSON, default=list)                            # 势力动态 [{"name":"","status":"","distance":"","change":""}]
    undercurrents = Column(JSON, default=list)                     # 暗线运行 [{"name":"","status":"","distance":"","progress":""}]
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "chapter", name="uq_world_state_project_chapter"),)


class WorldEvent(Base):
    """世界事件：每章 world_engine 产出的台上/台下事件。

    借鉴 bishu-novel world_events.json。
    """
    __tablename__ = "world_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    on_camera_events = Column(JSON, default=list)                  # 镜头内事件（≤3条）
    off_camera_events = Column(JSON, default=list)                 # 镜头外事件
    undercurrent_progress = Column(JSON, default=list)             # 暗线进展 [{"name":"","progress_percent":0,"next_milestone":""}]
    power_shift = Column(JSON, default=list)                       # 势力格局变化 [{"from":"","to":"","type":"","amount":""}]
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "chapter", name="uq_world_event_project_chapter"),)


# ── 叙事线系统（P0）──────────────────────────────────
# 线：一条完整剧情脉络。标签固定维度：主线/支线 × 明线/暗线；line_type 自定义（复仇线/时间线…）。

class Storyline(Base):
    """叙事线。"""
    __tablename__ = "storylines"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    line_type = Column(String(100), default="")          # 自定义类型（可空）
    tags = Column(JSON, default=list)                     # ["主线"/"支线", "明线"/"暗线"]
    status = Column(String(20), default="active")         # active/paused/resolved/abandoned
    progress = Column(Integer, default=0)                 # 0-100
    summary = Column(String(500), default="")
    notes = Column(Text, default="")
    planned_resolve_chapter = Column(Integer, default=0)
    volume = Column(String(100), default="")
    last_active_chapter = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    nodes = relationship("StorylineNode", back_populates="storyline",
                         cascade="all, delete-orphan")


class StorylineNode(Base):
    """线上的节点：伏笔（引用）/ 事件 / 里程碑。"""
    __tablename__ = "storyline_nodes"

    id = Column(Integer, primary_key=True, index=True)
    storyline_id = Column(Integer, ForeignKey("storylines.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    node_type = Column(String(20), default="event")       # foreshadow/event/milestone
    foreshadow_id = Column(String(50), default="")        # 可空；关联 foreshadows.foreshadow_id
    chapter = Column(Integer, default=0)
    title = Column(String(200), default="")
    description = Column(Text, default="")
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    storyline = relationship("Storyline", back_populates="nodes")


class StorylineRelation(Base):
    """线-线交汇关系。"""
    __tablename__ = "storyline_relations"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_storyline_id = Column(Integer, ForeignKey("storylines.id", ondelete="CASCADE"), nullable=False)
    target_storyline_id = Column(Integer, ForeignKey("storylines.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(20), default="merge")   # merge/intersect/parallel/conflict
    chapter = Column(Integer, default=0)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Location(Base):
    """小说地理地点：用于地图图谱。

    地点按层级组织（大陆→城市→附属城→街区/街道→建筑/地标），
    通过 parent_name 指向父级形成树，location_relationships 表定义道路/传送等平级关系。
    tier 表示层级（continent/kingdom/region/city/town/district/site/dungeon/landmark/other），
    layer 表示空间领域（surface/celestial/underworld/underwater/realm/other）。
    ruler 为城主/掌管者（角色名），plot_role 为剧情作用，unlocked_chapter 为剧情解锁章节。
    """
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    type = Column(String(50), default="city")           # city/region/landmark/secret/dungeon/other
    description = Column(Text, default="")
    parent_name = Column(String(200), default="")       # 所属上级地点名（如 "长安城" 属于 "大唐帝国"）
    coord_x = Column(Integer, default=0)                 # 地图坐标 X（用于初始布局）
    coord_y = Column(Integer, default=0)                 # 地图坐标 Y
    importance = Column(String(50), default="")          # 主城/枢纽/边陲/秘境
    tier = Column(String(50), default="")                # 层级: continent/kingdom/region/city/town/district/site/dungeon/landmark/other
    layer = Column(String(50), default="surface")        # 空间领域: surface/celestial/underworld/underwater/realm/other
    ruler = Column(String(200), default="")              # 城主/掌管者（角色名，多个用顿号分隔）
    plot_role = Column(Text, default="")                 # 剧情作用：该地点在剧情中的定位（如"主角重生点/最终决战地"）
    unlocked_chapter = Column(Integer, default=0)        # 剧情解锁章节：0=未解锁，>0=第 N 章起已解锁
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_location_project_name"),)


class LocationRelationship(Base):
    """地点间连接关系：道路/相邻/包含/传送等。"""
    __tablename__ = "location_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_location = Column(String(200), nullable=False)
    target_location = Column(String(200), nullable=False)
    relation_type = Column(String(50), default="road")  # road/adjacent/contains/portal/warzone
    distance = Column(String(50), default="")            # "300里"/"3天路程" 等
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "source_location", "target_location", "relation_type", name="uq_loc_rel"),)


class Graph(Base):
    """小说内容图谱：用户手动新建或一键生成的可视化图谱。

    支持五种类型：characters（人物关系）/ factions（势力关系）/
    foreshadows（伏笔网络）/ chapters（章节脉络）/ map（地图）/ custom（自由画布）。
    graph_data 存 ReactFlow 的 {nodes, edges} JSON。
    """
    __tablename__ = "graphs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    graph_type = Column(String(50), default="custom")  # characters|factions|foreshadows|chapters|map|custom
    description = Column(Text, default="")
    graph_data = Column(JSON, default=dict)            # {nodes: [...], edges: [...]}
    is_auto = Column(Boolean, default=False)           # True=一键生成（只读），False=手动编辑
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_graph_project_name"),)


class CustomWorkflow(Base):
    """用户自定义工作流：可视化编辑器创建的工作流定义。

    workflow_json 存完整的工作流定义（nodes/edges/start_position/inputs/agent_role），
    可被工作流执行器加载执行。
    """
    __tablename__ = "custom_workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id = Column(String(100), nullable=False)  # 用户定义的唯一 ID
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    workflow_json = Column(JSON, default=dict)        # 完整工作流定义
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "workflow_id", name="uq_custom_workflow_project_id"),)


class PostHocResult(Base):
    """后验裁决结果：每章 post_hoc 节点产出的设定漂移检测和故事差异裁决。

    借鉴 bishu-novel post-hoc 工作流，observer + arbiter 两轮 LLM 的完整结果。
    """
    __tablename__ = "post_hoc_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    # observer 产出的四类差异
    world_diff = Column(JSON, default=list)                        # 世界设定差异
    story_diff = Column(JSON, default=list)                        # 故事差异
    character_diff = Column(JSON, default=list)                    # 角色差异
    unplanned_events = Column(JSON, default=list)                  # 计划外事件
    # arbiter 的三类裁决
    world_adjudication = Column(JSON, default=list)                # 世界事实裁决 adopt/pending/conflict
    story_adjudication = Column(JSON, default=list)                # 故事差异确认 landed/missed/deviated
    event_classification = Column(JSON, default=list)              # 事件归类 hook/debt/discard
    summary = Column(JSON, default=dict)                           # 统计摘要 {"total_issues":0,"critical_count":0,...}
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "chapter", name="uq_post_hoc_project_chapter"),)


def migrate_db(engine) -> None:
    """SQLite 轻量迁移：创建缺失表、为已存在表补上新列，并统一时间戳列类型。"""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            try:
                table.create(bind=engine)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"migrate_db create table {table.name}: {exc}")
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing or col.primary_key:
                continue
            try:
                type_sql = col.type.compile(dialect=engine.dialect)
                # SQLite 不允许 ADD COLUMN 加 NOT NULL 且无默认值的列，自动补 SQL 默认值并保留 NOT NULL 约束
                if col.nullable is False and col.server_default is None:
                    if isinstance(col.type, Boolean):
                        type_sql += " DEFAULT 0 NOT NULL"
                    elif isinstance(col.type, Integer):
                        type_sql += " DEFAULT 0 NOT NULL"
                    elif isinstance(col.type, (String, Text)):
                        type_sql += " DEFAULT '' NOT NULL"
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {type_sql}"))
                    conn.commit()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"migrate_db skip {table.name}.{col.name}: {exc}")

    # 统一时间戳列类型：将仍保留为 String 的 created_at/updated_at 迁移为 DATETIME
    try:
        from novel_agent.bible.migrations.migrate_timestamp_columns import migrate_with_engine
        migrate_with_engine(engine)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"migrate_db timestamp migration: {exc}")
