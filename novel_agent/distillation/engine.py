"""蒸馏引擎：文本拆分 -> 多轮 LLM 蒸馏 -> Skill 生成 -> 技能融合 -> 效果对比。

核心流程：
1. import_text 导入作品并按 ≤10万字 智能拆分（优先章节边界）
2. distill_chunk 对每个片段做多轮蒸馏（3 个维度：风格/语言/结构）
3. generate_skill 把蒸馏结果固化为 Skill（DB 记录 + project_data/skills/*.json）
4. fuse_skills 按权重融合多个 Skill（支持"九合一"等模式）
5. compare_generate 对比"无章纲直出" vs "加载蒸馏 Skill 直出"
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from novel_agent.config import load_config
from novel_agent.distillation.store import DistillationStore, get_store
from novel_agent.llm.client import LLMClient
from novel_agent.state_common import DistillStatus
from novel_agent.utils.json_output import parse_json_safe

logger = logging.getLogger(__name__)

# 单片段最大字符数（≤10万字）
MAX_CHUNK_CHARS = 100000

# 章节标题正则：第X章/第X回/第X节/第X卷（中文数字或阿拉伯数字）
_CHAPTER_RE = re.compile(
    r"(?m)^\s*第[0-9零一二三四五六七八九十百千万两]+[章回卷节][^\n]*$"
)

# 蒸馏维度定义：round_num -> (维度名, 分析要点)
# 参考 Works DNA Extractor 的 16 层 DNA + 网文拆书方法论，精选 12 个语义维度。
# 1-7 为文笔/技法维度（向后兼容），8-12 为网文实战维度（设定/爽点/钩子/对话/反派）。
# 蒸馏时可自由勾选要分析的维度（默认全部）。
# 13-15 为「人味统计指纹」维度：直接对齐 AI 检测器（朱雀/GPTZero/Turnitin）的统计信号，
# 让"蒸馏输出的指纹"与"检测引擎的指纹"同一套，源头注入即可降低 AI 率。
ROUND_DIMENSIONS: dict[int, tuple[str, str]] = {
    1: ("写作风格特征", "叙事节奏、对话风格、描写习惯、情感表达方式"),
    2: ("语言特征", "用词偏好、句式结构、修辞手法、标点使用习惯"),
    3: ("故事结构特征", "情节推进方式、冲突设计、伏笔埋设、节奏控制"),
    4: ("叙事引擎", "驱动读者翻页的核心动力：悬念钩子、信息差、期待感制造、爽点释放节奏"),
    5: ("信息控制", "作者何时给读者什么信息：悬念吊法、伏笔隐藏深度、视角信息差、反转铺垫"),
    6: ("人物塑造技法", "角色出场方式、性格展现手法、对话辨识度、成长弧线设计、群像管理"),
    7: ("情感算法", "情绪曲线设计、共情锚点设置、情感落差制造、读者情绪引导路径"),
    8: ("世界观与设定", "题材融合方式、力量体系/金手指规则、舞台规则与禁忌、时代背景质感"),
    9: ("爽点设计", "爽点类型（打脸/碾压/逆袭/收获/智谋）、铺垫→释放模式、爽点密度与间隔"),
    10: ("章节钩子", "章节结尾断章技巧、悬念抛出方式、金句钩子、开篇抓人手法"),
    11: ("对话与台词", "对话占文本比例、角色语言辨识度、对话推动剧情的方式、潜台词运用"),
    12: ("反派与配角", "反派动机自洽与不降智、配角功能定位、工具人规避、人物关系张力"),
    13: ("节奏与句长指纹", "句长分布（短/中/长句占比）、对话占比、段落长短变化度——检测器第一信号（burstiness）的源头指纹"),
    14: ("禁词与套路词表", "原书回避的 AI 高频词与套路句式（如'不禁/仿佛/总而言之/不是…而是…'）——生成与检测共用同一份禁词表"),
    15: ("密度目标", "形容词密度、破折号密度、连接词密度、重复词密度的控制习惯——各检测器的词法统计信号"),
    16: ("动作与打斗", "打斗段落节奏（起手→交锋→转折→收束）、动作描写粒度（招式/身体细节/环境交互）、力量感与压迫感表达、紧张感与胜负悬念营造"),
    17: ("内心与心理", "内心独白风格（直接/隐喻/意识流）、情绪层次递进、内心冲突的构建方式（纠结/抉择/成长）、心理信息的投放节奏"),
    18: ("环境与描写", "氛围营造手法（光线/声音/气味/温度）、感官细节运用、环境借景叙事（景随情变）、描写克制度（不堆砌/留白）"),
    19: ("过渡与节奏", "场景间过渡方式（时间跳转/地点切换/情绪衔接/黑场）、场景衔接技巧、节奏换挡（紧张↔舒缓）、时间线/视角/空间连续性保持"),
}

# 蒸馏维度 → 适用 Agent（注入过滤用）。
# 每个维度产出的 Skill 会打上 agent_roles 标签，生成流程按当前 agent_type 过滤注入，
# 实现"每个 agent 只看自己负责维度的方法论"，避免全部维度全量注入撑爆上下文。
DIMENSION_AGENTS: dict[int, list[str]] = {
    1: ["novel-writer", "novel-single-writer", "novel-style-profiler", "novel-polisher", "novel-professional-polisher"],
    2: ["novel-writer", "novel-single-writer", "novel-storyboard-integrator"],
    3: ["novel-writer", "novel-single-writer", "novel-story-planner", "novel-outliner", "novel-volume-outliner"],
    4: ["novel-story-planner"],
    5: ["novel-director", "novel-outliner"],
    6: ["novel-character-skeleton", "novel-character-belief", "novel-character-deep", "novel-character-maintainer"],
    7: ["novel-palette-critic", "novel-writer", "novel-single-writer"],
    8: ["novel-worldbuilder-corelaws", "novel-worldbuilder-spacetime", "novel-worldbuilder-society",
        "novel-worldbuilder-historyculture", "novel-worldbuilder-existence", "novel-worldbuilder-information"],
    9: ["novel-writer", "novel-single-writer", "novel-storyboard-integrator"],
    10: ["novel-director", "novel-outliner"],
    11: ["novel-dialogue-writer", "novel-character-voice"],
    12: ["novel-character-maintainer"],
    13: ["novel-writer", "novel-single-writer", "novel-storyboard-integrator", "novel-self-critic", "novel-polisher"],
    14: ["novel-writer", "novel-single-writer", "novel-self-critic", "novel-polisher", "novel-professional-polisher"],
    15: ["novel-writer", "novel-single-writer", "novel-storyboard-integrator", "novel-self-critic", "novel-polisher"],
    16: ["novel-action-writer"],
    17: ["novel-internal-writer"],
    18: ["novel-description-writer"],
    19: ["novel-transition-writer", "novel-storyboard-integrator"],
}

# 专属模板维度集：这些维度使用各自的结构化输出规格（产出 agent 可直接执行的结构化字段）
_SPECIAL_SPEC_DIMS: dict[int, str] = {
    8: "_WORLD", 9: "_SATISFACTION", 10: "_HOOK", 11: "_DIALOGUE",
    16: "_ACTION", 17: "_INNER", 18: "_DESCRIPTION", 19: "_TRANSITION",
}

_DISTILL_SYSTEM = (
    "你是一位资深的网文写作风格分析专家，擅长从优秀作品中反向工程出可复用的写作方法论。"
    "你的分析必须具体、可执行，避免空泛的文学评论。每条手法都要附带原文例证。"
    "所有规则都是写作倾向而非绝对红线：当表达需要（情绪高潮、揭示关键信息、复杂场面）时，"
    "优先保证内容准确有力，可适度违背软规则；只有 hard_rules 是必须遵守的。"
    "禁止使用'单句不得超过X字'这类逐句硬性数字限制，数字只允许用于整体比例"
    "（如'长句占比≤30%'）或避免整齐划一的变化度要求（如'避免连续3句以上长度相近'）。"
)

# 多级蒸馏：浓缩提炼用的 system prompt（把一批碎片特征浓缩成精炼总纲）
_CONDENSE_SYSTEM = (
    "你是一位资深的网文写作风格提炼专家。下面是同一批作品蒸馏得到的多个写作特征分析片段。"
    "你的任务：把它们提炼浓缩成一份精炼、可执行的写作风格总纲——合并重复项、去粗取精、"
    "保留共性规律与可操作规则，丢弃琐碎或重复的细节。不要照抄原文，用自己的话概括；"
    "输入越冗余，压缩得越狠。"
    "所有规则都是写作倾向而非绝对红线：表达需要时可适度违背软规则，只有 hard_rules 是必须遵守的；"
    "禁止'单句不得超过X字'这类逐句硬限，数字只用于整体比例或变化度要求。"
)

_CONDENSE_OUTPUT_SPEC = """【输出要求】
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{
  "name": "总纲名称（≤12字，概括这批特征的核心）",
  "description": "一句话概括浓缩后的风格总纲",
  "signature_moves": [
    {"pattern": "可复现的写作手法（具体可操作）", "evidence": "原书例证（简短摘录）", "apply": "写作时如何落地", "exception": "何时可违背"}
  ],
  "hard_rules": ["极少数真正的红线（≤3条）"],
  "soft_guidelines": [
    {"rule": "倾向性规则（可用整体比例或变化度要求）", "why": "为什么这样写", "flexibility": "何时可适度违背"}
  ],
  "anti_patterns": ["禁止的写法", "..."],
  "tags": ["2-5 个标签", "..."]
}
数量要求：signature_moves 4-8 条，hard_rules ≤3 条，soft_guidelines 3-6 条，anti_patterns 2-4 条。
禁止'单句不得超过X字'这类逐句硬限；数字只用于整体比例（如'长句占比≤30%'）或变化度（如'避免连续3句以上长度相近'）。"""

# 三级浓缩（说明书）专用输出规格：在总纲基础上加"维度索引"，
# 告诉模型本书有哪些维度的二级总纲、每个对应写作哪个环节、何时翻哪份——对应
# 「三级=说明书、二级=规格、一级=素材库」分层：说明书导览二级，二级指引一级。
_CONDENSE_INDEX_OUTPUT_SPEC = """【输出要求】
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{
  "name": "说明书名称（≤12字，如'全书风格说明书'）",
  "description": "一句话概括本书整体风格与写法",
  "dimension_index": [
    {"dimension": "维度名（如'爽点设计'）", "writing_stage": "对应写作环节（如'写高潮章/打脸场景时'）", "how_to_use": "何时翻这份二级总纲、重点看什么（具体可操作）"}
  ],
  "signature_moves": [
    {"pattern": "全书最核心的可复现写作手法（具体可操作）", "evidence": "原书例证（简短摘录）", "apply": "写作时如何落地", "exception": "何时可违背"}
  ],
  "hard_rules": ["极少数真正的红线（≤3条）"],
  "soft_guidelines": [
    {"rule": "倾向性规则", "why": "为什么这样写", "flexibility": "何时可适度违背"}
  ],
  "anti_patterns": ["禁止的写法（避免 AI 味/反例，必须 ≥6 条）", "..."],
  "tags": ["2-5 个标签", "..."]
}
数量要求：dimension_index 必须覆盖输入中出现的每个维度（一个维度一条）；signature_moves 4-8 条；
hard_rules ≤3 条；soft_guidelines 3-6 条；anti_patterns ≥6 条。
禁止'单句不得超过X字'这类逐句硬限；数字只用于整体比例或变化度要求。
dimension_index 的写作环节与用法必须基于各维度总纲的实际内容推断，禁止凭空编造。"""

# 13-15 轮（人味统计指纹）专用输出规格：产出可量化指纹，供检测引擎/注入链路共用
_SIGNATURE_OUTPUT_SPEC = """【输出要求】
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{
  "name": "指纹名称（≤12字，如'雷霆节奏'）",
  "description": "一句话概括该指纹",
  "rhythm_profile": {
    "short_sentence_ratio": "15字内短句占比（整体比例，如 0.35，只允许整体比例，禁止逐句硬限）",
    "long_sentence_ratio": "40字以上长句占比（整体比例，如 0.20）",
    "dialogue_ratio": "对话占文本比例（如 0.25，网文通常 0.15-0.35）",
    "para_variation": "段落长短变化度描述（如'对话段1-2行，场景段4-6行，长短交替'）",
    "burstiness_note": "原书节奏给读者的直观感受（如'每3-5句必有一个短句砸点'）"
  },
  "ban_words": ["原书几乎不用的 AI 高频词/套路词（仅列原书回避的，如'不禁'、'仿佛'）", "..."],
  "density_targets": {
    "adj_density": "形容词控制（整体比例或直观描述，如'千字≤2个模糊形容词'）",
    "dash_density": "破折号控制（如'一章≤2个'）",
    "connector_density": "连接词控制（如'每千字≤4个套路连接词'）",
    "repetition": "重复词控制（如'同一词千字重复≤2次'）"
  },
  "tags": ["2-3 个标签", "..."]
}
只允许整体比例/变化度要求，禁止'每句不得超过X字'这类逐句硬限。每个字段必须是从原文实际观察到的，禁止凭空编造。"""

_JSON_OUTPUT_SPEC = """【输出要求】
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{
  "name": "特征集名称（≤12字，概括该维度的核心风格）",
  "description": "一句话概括该片段在此维度的风格",
  "signature_moves": [
    {"pattern": "可复现的写作手法（具体、可操作，如'爽点释放前必先铺垫压抑'）", "evidence": "原文例证（从片段摘录一两句）", "apply": "写作时如何落地（怎么做）", "exception": "何时可以违背（如情绪高潮、角色转变等场景）"}
  ],
  "hard_rules": ["极少数真正不能违反的红线（≤3条，尽量不用纯数字规则）", "..."],
  "soft_guidelines": [
    {"rule": "倾向性规则（可用整体比例如'长句占比≤30%'，或变化度要求如'避免连续3句以上长度相近'；禁止'单句不得超过X字'这类逐句硬限）", "why": "为什么这样写（原作的用意）", "flexibility": "何时可适度违背"}
  ],
  "anti_patterns": ["禁止的写法（避免 AI 味/反例，必须 ≥6 条——最锐利的方法论藏在反例里，只列正面会产出肤浅结果）", "..."],
  "tags": ["标签", "..."]
}
数量要求：signature_moves 4-8 条，hard_rules ≤3 条，soft_guidelines 3-6 条，anti_patterns ≥6 条，tags 2-5 个。"""

# 维度专属模板：在通用结构（signature_moves/hard_rules/soft_guidelines/anti_patterns/tags）之上，
# 各专属维度额外产出结构化字段，让对应 agent 拿到可直接执行的方法论。
# 公共部分（每个专属模板都要求）：signature_moves 4-8 条、hard_rules ≤3、soft_guidelines 3-6、
# anti_patterns ≥6（黑名单是方法论的核心，最锐利的理解藏在反例里）、tags 2-5 个。

_SPECIAL_SPEC_TEMPLATE = """【输出要求】
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{
  "name": "{dim_name}特征集（≤12字）",
  "description": "一句话概括该片段在此维度的风格",
  {extra_fields}
  "signature_moves": [
    {{"pattern": "可复现的写作手法（具体、可操作）", "evidence": "原文例证（从片段摘录一两句）", "apply": "写作时如何落地", "exception": "何时可以违背"}}
  ],
  "hard_rules": ["极少数真正不能违反的红线（≤3条）", "..."],
  "soft_guidelines": [
    {{"rule": "倾向性规则（可用整体比例或变化度要求，禁止逐句硬限）", "why": "为什么这样写", "flexibility": "何时可适度违背"}}
  ],
  "anti_patterns": ["禁止的写法（必须 ≥6 条）", "..."],
  "tags": ["2-5 个标签", "..."]
}
数量要求：signature_moves 4-8 条，hard_rules ≤3 条，soft_guidelines 3-6 条，anti_patterns ≥6 条，tags 2-5 个。
所有专属字段必须从原文实际观察提炼，禁止凭空编造；禁止'单句不得超过X字'这类逐句硬限，数字只用于整体比例或变化度要求。"""

# 专属维度 → 额外结构化字段（挂在顶层 JSON，渲染时按维度名输出小节）
_SPECIAL_FIELDS: dict[str, tuple[str, dict[str, str]]] = {
    # (维度名, {字段key: 字段含义})
    "_WORLD": ("世界观与设定", {
        "power_system": "力量体系/金手指规则：获取方式、升级路径、使用代价、边界禁忌（原书如何设定与约束）",
        "setting_reveal": "设定投放方式：世界观信息如何借对话/行动/环境自然呈现（不写说明书）",
        "terminology": "本书专属术语与用法（词条+正确用法）",
        "consistency": "一致性维护规则：设定与力量体系如何自洽、不崩坏",
    }),
    "_SATISFACTION": ("爽点设计", {
        "satisfaction_types": "爽点类型清单（打脸/碾压/逆袭/收获/智谋/装逼…原书惯用哪些）",
        "setup_release": "铺垫→释放模式：压抑多久、如何引爆、释放后的余韵处理",
        "density": "爽点密度与间隔（每千字几个、间隔多远、何时密集何时稀疏）",
    }),
    "_HOOK": ("章节钩子", {
        "hook_types": "断章钩子类型清单（悬念/危机/转折/金句/身份揭示…原书惯用哪些）",
        "hook_position": "钩子出现的位置与频率（章末/章首/中间）",
        "cliffhanger_style": "断章具体写法：停在动作/对话/信息揭示的哪一刻、如何制造意犹未尽",
        "opening_hooks": "开篇抓人手法（首段如何建立冲突或悬念）",
    }),
    "_DIALOGUE": ("对话与台词", {
        "dialogue_ratio": "对话占比与节奏（整体比例）",
        "voice_markers": "角色语言辨识标志（口头禅/句式/用词/语速特征）",
        "subtext_style": "潜台词写法：言外之意如何暗示（不直说）",
        "dialogue_action": "对话中如何夹杂动作/神态推进（对话不悬空）",
    }),
    "_ACTION": ("动作与打斗", {
        "fight_rhythm": "打斗段落节奏：起手→交锋→转折→收束的节拍与篇幅分配",
        "action_beats": "动作描写粒度：招式/身体细节/环境交互的具体写法",
        "power_feel": "力量感与压迫感的表达手法（如何让读者感受到强弱）",
        "tension_techniques": "打斗中紧张感与胜负悬念的营造（何时铺垫何时爆发）",
    }),
    "_INNER": ("内心与心理", {
        "inner_voice": "内心独白风格（直接/隐喻/意识流/动作化）",
        "emotion_layers": "情绪层次递进：表层反应→真实动机的展现顺序",
        "conflict_build": "内心冲突的构建方式（纠结/抉择/成长瞬间如何处理）",
        "reveal_pacing": "心理信息投放节奏（不冗长、与外部剧情交替）",
    }),
    "_DESCRIPTION": ("环境与描写", {
        "atmosphere": "氛围营造手法（光线/声音/气味/温度/色调如何组合）",
        "sensory_detail": "感官细节运用（视觉/听觉/触觉/嗅觉的选取与比例）",
        "setting_narrative": "环境借景叙事：景物如何随人物心境变化（景随情变）",
        "restraint": "描写克制度：不堆砌、留白、与剧情节奏配合",
    }),
    "_TRANSITION": ("过渡与节奏", {
        "transition_types": "场景过渡方式清单（时间跳转/地点切换/情绪衔接/黑场…原书惯用哪些）",
        "scene_link": "场景衔接技巧（承上启下/并行对照/反差切换）",
        "rhythm_shift": "节奏换挡：紧张↔舒缓的切换点与手法",
        "continuity": "时间线/视角/空间连续性维护（不跳戏不混乱）",
    }),
}

# 效果对比用的基础系统提示词
_COMPARE_BASE_SYSTEM = (
    "你是一位网文写手。请根据用户的写作要求直接生成小说正文，"
    "不要输出章节大纲、不要解释，只输出正文。"
)

# SSE 事件回调类型
OnEvent = Callable[[dict], Awaitable[None]]


class DistillationEngine:
    """蒸馏引擎：拆分、蒸馏、Skill 生成、融合、对比。"""

    def __init__(self, store: DistillationStore | None = None):
        self.store = store or get_store()

    # ------------------------------------------------------------------
    # 文本拆分
    # ------------------------------------------------------------------
    @staticmethod
    def split_text(content: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
        """智能拆分：优先按"第X章"边界拆分，单章太长时按段落拆分，超长段落硬切。

        Args:
            content: 原始文本
            max_chars: 单片段最大字符数

        Returns:
            片段列表（每个 ≤ max_chars，最后一个除外若原文本身无法再拆）
        """
        content = content.strip()
        if not content:
            return []
        if len(content) <= max_chars:
            return [content]

        # 1. 按章节标题切分得到 segments（含章前 preamble）
        matches = list(_CHAPTER_RE.finditer(content))
        segments: list[str] = []
        if matches:
            if matches[0].start() > 0:
                preamble = content[: matches[0].start()].strip()
                if preamble:
                    segments.append(preamble)
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                segments.append(content[m.start():end].strip())
        else:
            segments = [content]

        # 2. 贪心打包 segments 到 ≤max_chars 的 chunk；单 segment 过长则按段落拆
        chunks: list[str] = []
        current = ""
        for seg in segments:
            if len(seg) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(DistillationEngine._split_long_segment(seg, max_chars))
            elif current and len(current) + len(seg) + 1 > max_chars:
                chunks.append(current)
                current = seg
            else:
                current = f"{current}\n\n{seg}" if current else seg
        if current:
            chunks.append(current)
        return [c for c in chunks if c.strip()]

    @staticmethod
    def _split_long_segment(segment: str, max_chars: int) -> list[str]:
        """按段落拆分超长章节；单段落仍超长时硬切。"""
        paragraphs = [p for p in re.split(r"\n\s*\n|\n", segment) if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            para = para.strip()
            if len(para) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                # 硬切
                for i in range(0, len(para), max_chars):
                    chunks.append(para[i: i + max_chars])
            elif current and len(current) + len(para) + 1 > max_chars:
                chunks.append(current)
                current = para
            else:
                current = f"{current}\n{para}" if current else para
        if current:
            chunks.append(current)
        return chunks

    # ------------------------------------------------------------------
    # 导入
    # ------------------------------------------------------------------
    def import_text(self, title: str, content: str, source_type: str = "file",
                    file_path: str | None = None,
                    max_chars: int = MAX_CHUNK_CHARS) -> dict:
        """导入文本：自动拆分并写入 works + chunks。

        Returns:
            {"work_id": int, "chunk_count": int, "total_chars": int}
        """
        content = (content or "").strip()
        if not content:
            raise ValueError("导入内容为空")
        chunks = self.split_text(content, max_chars=max_chars)
        work_id = self.store.create_work(
            title=title, source_type=source_type, file_path=file_path,
            total_chars=len(content), chunk_count=len(chunks),
        )
        for idx, chunk in enumerate(chunks):
            self.store.create_chunk(work_id, idx, chunk)
        logger.info("导入作品《%s》: %d 字 -> %d 个片段", title, len(content), len(chunks))
        return {"work_id": work_id, "chunk_count": len(chunks), "total_chars": len(content)}

    # ------------------------------------------------------------------
    # 蒸馏
    # ------------------------------------------------------------------
    @staticmethod
    def build_round_prompt(round_num: int, content: str) -> tuple[str, str]:
        """构造单轮蒸馏的 (system, user) prompt。

        13-15 轮（人味统计指纹）使用独立输出规格，产出可量化指纹；
        8/9/10/11/16/17/18/19 轮使用维度专属输出规格（结构化专属字段）；
        其余维度使用通用规格。
        """
        dim_name, dim_points = ROUND_DIMENSIONS.get(round_num, ROUND_DIMENSIONS[1])
        spec_key = _SPECIAL_SPEC_DIMS.get(round_num)
        if spec_key:
            spec = DistillationEngine._build_special_output_spec(spec_key)
        else:
            spec = _SIGNATURE_OUTPUT_SPEC if round_num in (13, 14, 15) else _JSON_OUTPUT_SPEC
        user = (
            f"请对以下小说文本片段进行第 {round_num} 轮蒸馏分析，"
            f"提取【{dim_name}】。\n\n"
            f"分析维度：{dim_points}\n\n"
            f"【文本片段】\n{content}\n\n"
            f"{spec}"
        )
        return _DISTILL_SYSTEM, user

    @staticmethod
    def _build_special_output_spec(dim_key: str) -> str:
        """生成维度专属输出规格（通用结构 + 该维度的结构化字段）。"""
        dim_name, fields = _SPECIAL_FIELDS[dim_key]
        extra = ",\n  ".join(f'"{k}": "{v}"' for k, v in fields.items())
        return _SPECIAL_SPEC_TEMPLATE.format(dim_name=dim_name, extra_fields=extra)

    async def distill_chunk(self, chunk_id: int, round_num: int,
                            client: LLMClient, reuse_failed_round: bool = False,
                            thinking: bool | None = None) -> dict:
        """对单个片段执行一轮蒸馏，并生成对应 Skill。

        Args:
            reuse_failed_round: 补蒸馏模式——若该片段该轮已有未成功的记录（failed /
                中断残留的 running），复用其 round_id 覆盖结果，避免 DB 累积重复记录。
            thinking: 是否开启思考模式（None=跟随模型/provider 默认）。
                火山 coding 网关不兼容思考参数（带上后请求挂起），由 client 自动降级关闭。
        """
        chunk = self.store.get_chunk(chunk_id)
        if not chunk:
            raise ValueError(f"片段不存在: chunk_id={chunk_id}")
        system, user = self.build_round_prompt(round_num, chunk["content"])
        round_id = None
        if reuse_failed_round:
            existing = self.store.get_round(chunk_id, round_num)
            if existing and existing["status"] != DistillStatus.DONE.value:
                round_id = existing["id"]
        if round_id is None:
            round_id = self.store.create_round(chunk_id, round_num, user)
        try:
            result_text = await client.generate(
                user, system=system, node_name="distill",
                thinking=thinking,  # None → client 按 config.enable_thinking（模型管理页配置）
            )
        except Exception:
            self.store.complete_round(round_id, "", "", status=DistillStatus.FAILED.value)
            raise
        skill_data = parse_json_safe(result_text)
        if skill_data is None:
            # JSON 解析失败：保留原文，用兜底结构生成 Skill
            logger.warning("蒸馏结果 JSON 解析失败 (chunk=%d round=%d)，使用兜底结构",
                           chunk_id, round_num)
            skill_data = {
                "name": f"第{round_num}轮蒸馏特征",
                "description": "（LLM 输出未按 JSON 格式返回，已保留原始分析文本）",
                "signature_moves": [],
                "hard_rules": [],
                "soft_guidelines": [{"rule": result_text.strip(), "why": "", "flexibility": ""}],
                "anti_patterns": [],
                "tags": [],
            }
        self.store.complete_round(
            round_id, result_text,
            json.dumps(skill_data, ensure_ascii=False), status=DistillStatus.DONE.value,
        )
        skill = self.generate_skill(
            work_id=chunk["work_id"], chunk_index=chunk["chunk_index"],
            round_num=round_num,
        )
        return {
            "round_id": round_id,
            "skill_id": skill["id"],
            "skill_name": skill["name"],
            "skill_data": skill_data,
        }

    async def distill_work(self, work_id: int, client: LLMClient,
                           dimensions: list[int] | None = None,
                           levels: int = 1,
                           retry_failed: bool = False,
                           skip_done_rounds: bool = False,
                           on_event: OnEvent | None = None,
                           is_cancelled=None,
                           enable_thinking: bool | None = None) -> dict:
        """对整部作品的所有片段执行多轮蒸馏，逐事件回调进度。

        is_cancelled: 可选回调（返回 bool）。在片段/轮次边界检查，为 True 时
        优雅停止（已完成的片段/轮次产物保留），不再启动新的 LLM 调用。

        Args:
            dimensions: 要蒸馏的维度编号列表（1..19，见 ROUND_DIMENSIONS；
                13-15 为人味统计指纹维度，16-19 为动作/内心/描写/过渡专项维度）。
                None 时默认分析全部维度。
            levels: 多级蒸馏级数（1=碎片，2=二次浓缩，3=三次浓缩）。
            retry_failed: 补蒸馏模式——只重跑失败的片段/轮次（跳过已 done 的），
                不重复已成功的结果。用于部分失败/中断后的补齐，省时省钱。

        事件：chunk_start / round_start / round_done / round_failed /
              skill_created / chunk_done / work_done
        多级蒸馏（levels ≥ 2）：一次蒸馏完成后，把全部碎片 Skill 交给 LLM
        逐级浓缩提炼（levels=2 二次蒸馏、levels=3 三次蒸馏），每级产出 1 个精炼总技能。
        浓缩事件：condense_start / condense_batch_start / condense_batch_done /
                  condense_done / condense_failed
        """
        work = self.store.get_work(work_id)
        if not work:
            raise ValueError(f"作品不存在: work_id={work_id}")
        chunks = self.store.list_chunks(work_id)
        if not chunks:
            raise ValueError(f"作品无片段: work_id={work_id}")
        dims = dimensions if dimensions else list(range(1, len(ROUND_DIMENSIONS) + 1))
        # 过滤非法维度编号，避免 SQL/进度越界
        dims = [d for d in dims if d in ROUND_DIMENSIONS]
        if not dims:
            raise ValueError("未选择任何有效的蒸馏维度")
        self.store.update_work_status(work_id, DistillStatus.DISTILLING.value)
        failed = 0
        cancelled = False

        def _is_cancelled() -> bool:
            return bool(is_cancelled and is_cancelled())

        for chunk in chunks:
            if _is_cancelled():
                cancelled = True
                break
            chunk_id = chunk["id"]
            # 补蒸馏模式：整片段已完成则跳过（保持原状态，不发事件）
            if retry_failed and chunk["status"] == DistillStatus.DONE.value:
                continue
            await self._emit(on_event, {
                "type": "chunk_start", "work_id": work_id,
                "chunk_id": chunk_id, "chunk_index": chunk["chunk_index"],
                "char_count": chunk["char_count"],
            })
            self.store.update_chunk_status(chunk_id, DistillStatus.DISTILLING.value)
            chunk_ok = True
            for round_num in dims:
                # 取消检查：片段/轮次边界优雅停止，不启动新的 LLM 调用
                if _is_cancelled():
                    cancelled = True
                    chunk_ok = False
                    break
                # 隔离模式：该轮已成功完成则跳过（不重复调用 LLM，不产生冗余记录）。
                # 用于"同一本书多次蒸馏不同维度"场景——每次只跑新维度，旧产物原样保留。
                if retry_failed or skip_done_rounds:
                    existing = self.store.get_round(chunk_id, round_num)
                    if existing and existing["status"] == DistillStatus.DONE.value:
                        continue
                await self._emit(on_event, {
                    "type": "round_start", "work_id": work_id,
                    "chunk_id": chunk_id, "chunk_index": chunk["chunk_index"],
                    "round_num": round_num,
                    "dimension": ROUND_DIMENSIONS.get(round_num, ("综合特征", ""))[0],
                })
                try:
                    result = await self.distill_chunk(
                        chunk_id, round_num, client,
                        reuse_failed_round=retry_failed,
                        thinking=enable_thinking,
                    )
                    await self._emit(on_event, {
                        "type": "round_done", "work_id": work_id,
                        "chunk_id": chunk_id, "chunk_index": chunk["chunk_index"],
                        "round_num": round_num, "round_id": result["round_id"],
                    })
                    await self._emit(on_event, {
                        "type": "skill_created", "work_id": work_id,
                        "chunk_index": chunk["chunk_index"], "round_num": round_num,
                        "skill_id": result["skill_id"], "skill_name": result["skill_name"],
                    })
                except Exception as e:
                    chunk_ok = False
                    failed += 1
                    logger.exception("蒸馏失败 (work=%d chunk=%d round=%d)",
                                     work_id, chunk_id, round_num)
                    await self._emit(on_event, {
                        "type": "round_failed", "work_id": work_id,
                        "chunk_id": chunk_id, "chunk_index": chunk["chunk_index"],
                        "round_num": round_num, "error": str(e),
                    })
            if not cancelled:
                self.store.update_chunk_status(chunk_id, DistillStatus.DONE.value if chunk_ok else DistillStatus.FAILED.value)
                await self._emit(on_event, {
                    "type": "chunk_done", "work_id": work_id,
                    "chunk_id": chunk_id, "chunk_index": chunk["chunk_index"],
                    "status": DistillStatus.DONE.value if chunk_ok else DistillStatus.FAILED.value,
                })

        # 多级蒸馏：对一次蒸馏产物逐级浓缩（二次/三次蒸馏）
        # 二级按维度分组浓缩（每维度 1 个总纲=规格），三级把全部二级总纲
        # 再浓缩成 1 个精华（说明书），对应「三级=说明书、二级=规格、一级=素材库」分层。
        if not cancelled and levels >= 2:
            source_skills = self.store.list_skills(work_id)
            if source_skills:
                for level in range(2, levels + 1):
                    await self._emit(on_event, {
                        "type": "condense_start", "level": level,
                        "source_count": len(source_skills),
                    })
                    condensed_list = await self.condense_skills(
                        source_skills, client, level=level, on_event=on_event,
                        group_by_dimension=(level == 2),
                    )
                    if not condensed_list:
                        failed += 1
                        await self._emit(on_event, {
                            "type": "condense_failed", "level": level,
                        })
                        break
                    source_skills = condensed_list

        if cancelled:
            # work 状态已由 cancel 端点置为 cancelled，这里不覆盖为 done/failed
            await self._emit(on_event, {
                "type": "cancelled", "work_id": work_id,
                "status": "cancelled", "dimensions": dims,
            })
            return {"status": "cancelled", "dimensions": dims, **self.store.progress(work_id)}

        final_status = (DistillStatus.DONE.value if failed == 0 else
                        (DistillStatus.FAILED.value if failed == len(chunks) * len(dims)
                         else DistillStatus.DONE_WITH_ERRORS.value))
        self.store.update_work_status(work_id, final_status)
        progress = self.store.progress(work_id)
        await self._emit(on_event, {
            "type": "work_done", "work_id": work_id,
            "status": final_status, "dimensions": dims, **progress,
        })
        return {"status": final_status, "dimensions": dims, **progress}

    @staticmethod
    async def _emit(on_event: OnEvent | None, event: dict) -> None:
        if on_event is not None:
            await on_event(event)

    # ------------------------------------------------------------------
    # 多级蒸馏：浓缩提炼
    # ------------------------------------------------------------------
    _CONDENSE_BATCH_BUDGET = 40000  # 每批输入字符预算（分批控制上下文）
    _FUSE_MAX_BLOCKS = 40  # 融合时每批最多块数，超出自动分批递归融合（数量不限）
    _FUSE_CONCURRENCY = 4  # 并行融合的并发数（多批同时提炼，受 LLM API 限流与连接池约束）

    async def condense_skills(self, skills: list[dict], client: LLMClient,
                              level: int, on_event: OnEvent | None = None,
                              group_by_dimension: bool = False) -> list[dict] | None:
        """把一批 Skill 交给 LLM 提炼浓缩成精炼总技能（第 level 级浓缩）。

        分批 → 每批一次 LLM 提炼 → 归并（递归）直到剩 1 块 → 生成总技能。
        产物：DB 记录（chunk_index=-1, round_num=level）+ skills 目录
              distill_w{id}_level{level}.json（二级按维度分组时为
              distill_w{id}_level{level}_d{dim}.json，每维度一个）。

        Args:
            group_by_dimension: True（二级浓缩）时按维度（skill.round_num，一级碎片
                的 round_num 即维度号）分组，每组浓缩成 1 个该维度总纲——
                对应「二级=规格」分层：每本书每个维度一份浓缩规格，供对应 agent 定向注入。
                False（三级及以上）时全部来源融合浓缩成 1 个精华（「三级=说明书」）。

        Returns:
            浓缩后的 skill dict 列表（每个维度一个）；无任何可浓缩内容返回 None
        """
        usable = [s for s in skills if (s.get("content") or "").strip()]
        if not usable:
            return None

        if group_by_dimension:
            groups: dict[int, list[dict]] = {}
            for s in usable:
                dim = s.get("round_num") or 0  # 一级碎片 round_num 即维度号
                groups.setdefault(dim, []).append(s)
            ordered = sorted(groups.items())  # 维度号升序，产出顺序稳定
        else:
            ordered = [(0, usable)]

        results: list[dict] = []
        for dim, group in ordered:
            single = await self._condense_group(
                group, client, level, on_event=on_event, dim=dim if dim else None)
            if single:
                results.append(single)
        return results or None

    async def _condense_group(self, skills: list[dict], client: LLMClient,
                              level: int, on_event: OnEvent | None = None,
                              dim: int | None = None) -> dict | None:
        """浓缩单组 Skill（一个维度或全部来源）成 1 个精炼总技能。"""
        blocks = [s.get("content") or "" for s in skills if (s.get("content") or "").strip()]
        if not blocks:
            return None
        safety = 0
        while len(blocks) > 1 and safety < 12:
            safety += 1
            batches = self._batch_texts(blocks, budget=self._CONDENSE_BATCH_BUDGET)
            new_blocks: list[str] = []
            for i, batch in enumerate(batches):
                if len(batches) > 1:
                    await self._emit(on_event, {
                        "type": "condense_batch_start", "level": level,
                        "batch": i + 1, "total": len(batches),
                    })
                try:
                    text = await self._llm_condense(batch, client, level)
                    if text.strip():
                        new_blocks.append(text.strip())
                except Exception as e:
                    logger.warning("浓缩批 %d/%d 失败（level=%d）: %s", i + 1, len(batches), level, e)
                if len(batches) > 1:
                    await self._emit(on_event, {
                        "type": "condense_batch_done", "level": level,
                        "batch": i + 1, "total": len(batches),
                    })
            blocks = new_blocks if new_blocks else ["\n\n".join(blocks)]
        final_text = blocks[0]

        data: dict = {}
        try:
            parsed = parse_json_safe(final_text)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            pass

        dim_name = ROUND_DIMENSIONS.get(dim, ("综合", ""))[0] if dim else ""
        if data:
            name = str(data.get("name") or "").strip() or \
                (f"{dim_name}·第{level}级" if dim_name else f"整书风格·第{level}级")
            description = str(data.get("description") or "").strip() or (
                f"对《{skills[0].get('work_title') or ''}》『{dim_name}』维度的第{level}级浓缩提炼"
                if dim_name else f"对全书蒸馏产物的第{level}级浓缩提炼")
            tags = data.get("tags") or [f"第{level}级浓缩"]
            if isinstance(tags, str):
                tags = [tags]
            content = self._compose_condensed_content(level, data, dim_name=dim_name)
        else:
            # LLM 未返回 JSON：把最终文本直接作为内容
            name = f"{dim_name}·第{level}级" if dim_name else f"整书风格·第{level}级"
            description = f"对全书蒸馏产物的第{level}级浓缩提炼"
            tags = [f"第{level}级浓缩"]
            content = final_text

        work_id = int(skills[0].get("work_id") or 0)
        work_title = skills[0].get("work_title") or ""
        file_name = f"distill_w{work_id}_level{level}"
        if dim is not None:
            file_name += f"_d{dim}"
        if (self._skills_dir() / f"{file_name}.json").exists():
            file_name = f"{file_name}_{uuid.uuid4().hex[:6]}"
        skill_id = self.store.create_skill(
            work_id=work_id, work_title=work_title,
            chunk_index=-1, round_num=level,  # chunk_index=-1 标记浓缩产物
            name=file_name, description=f"【{name}】{description}",
            content=content, tags=tags,
        )
        # 二级维度总纲是规则型（全量注入），按维度打 agent 标签定向注入；
        # agent_roles 沿用该维度的一级映射，保证三级「说明书」全量注入时不遗漏
        agent_roles = DIMENSION_AGENTS.get(dim, []) if dim is not None else []
        self._write_skill_file(file_name, name, description, content, tags,
                               status="active", category="rule",
                               agent_roles=agent_roles)
        logger.info("第%d级浓缩完成: %s (%d 个来源%s)", level, file_name,
                    len(skills), f"，维度={dim_name}" if dim_name else "")
        await self._emit(on_event, {
            "type": "condense_done", "level": level,
            "skill_id": skill_id, "skill_name": file_name, "name": name,
        })
        return self.store.get_skill(skill_id)

    @staticmethod
    def _batch_texts(blocks: list[str], budget: int) -> list[list[str]]:
        """把文本块按字符预算分批（保序）。

        单个块超过预算时截断到预算内，避免单次 LLM 调用输入超上限。
        """
        batches: list[list[str]] = []
        cur: list[str] = []
        cur_len = 0
        for b in blocks:
            if len(b) > budget:
                b = b[:budget]
            if cur and cur_len + len(b) > budget:
                batches.append(cur)
                cur, cur_len = [], 0
            cur.append(b)
            cur_len += len(b)
        if cur:
            batches.append(cur)
        return batches

    async def _llm_condense(self, batch_texts: list[str], client: LLMClient, level: int) -> str:
        """单批浓缩：LLM 提炼，返回浓缩文本（JSON 或 markdown）。

        level>=3（三级说明书）：要求输出含 dimension_index 维度索引——
        告诉模型本书有哪些维度的二级总纲、每个对应写作哪个环节、何时翻哪份。
        """
        spec = _CONDENSE_INDEX_OUTPUT_SPEC if level >= 3 else _CONDENSE_OUTPUT_SPEC
        if level >= 3:
            brief = (
                f"下面是本书 {len(batch_texts)} 个维度的二级总纲，请浓缩成一份"
                f"'写作风格说明书'，并生成维度索引（每个维度对应哪个写作环节、何时翻哪份总纲）：\n\n"
            )
        else:
            brief = (
                f"下面是 {len(batch_texts)} 段写作特征分析（按重要性排序），请提炼浓缩：\n\n"
            )
        user = (
            f"【第{level}级蒸馏 · 浓缩提炼】\n"
            + brief
            + "\n\n---\n\n".join(batch_texts)
            + "\n\n" + spec
        )
        return await client.generate(user, system=_CONDENSE_SYSTEM, node_name="distill_condense",
                                     thinking=False)

    @staticmethod
    def _render_style_body(skill_data: dict) -> list[str]:
        """把蒸馏结果的 v2 结构化 JSON 渲染成 markdown 主体（行列表）。

        兼容旧格式（features/guidelines）：老数据没有 v2 字段时按旧结构渲染。
        """
        lines: list[str] = []

        # 招牌手法（v2 核心块：模式+例证+落地+例外）
        moves = skill_data.get("signature_moves") or []
        if moves:
            lines.append("## 招牌手法（可复现的写作套路）")
            lines.append("")
            for i, m in enumerate(moves, 1):
                if isinstance(m, str):
                    lines.append(f"{i}. {m.strip()}")
                elif isinstance(m, dict):
                    pattern = str(m.get("pattern") or "").strip()
                    evidence = str(m.get("evidence") or "").strip()
                    apply = str(m.get("apply") or "").strip()
                    exception = str(m.get("exception") or "").strip()
                    if not pattern and not evidence:
                        continue
                    lines.append(f"{i}. **{pattern or '（未命名手法）'}**")
                    if evidence:
                        lines.append(f"   - 例证：{evidence}")
                    if apply:
                        lines.append(f"   - 落地：{apply}")
                    if exception:
                        lines.append(f"   - 例外：{exception}")
            lines.append("")

        # 红线（少而精，必须遵守）
        hard = skill_data.get("hard_rules") or []
        if hard:
            lines.append("## 不可违反的红线")
            lines.append("")
            for h in hard:
                if isinstance(h, dict):
                    h = str(h.get("rule") or h.get("pattern") or "").strip()
                if str(h).strip():
                    lines.append(f"- {str(h).strip()}")
            lines.append("")

        # 软性倾向（可适度违背，带 why 与例外）
        soft = skill_data.get("soft_guidelines") or []
        if soft:
            lines.append("## 写作倾向（软规则，表达需要时可适度违背）")
            lines.append("")
            for g in soft:
                if isinstance(g, str):
                    if g.strip():
                        lines.append(f"- {g.strip()}")
                elif isinstance(g, dict):
                    rule = str(g.get("rule") or "").strip()
                    if not rule:
                        continue
                    why = str(g.get("why") or "").strip()
                    flex = str(g.get("flexibility") or "").strip()
                    item = f"- **{rule}**"
                    if why:
                        item += f"（{why}）"
                    if flex:
                        item += f"；例外：{flex}"
                    lines.append(item)
            lines.append("")

        # 反模式（禁止的写法）
        anti = skill_data.get("anti_patterns") or []
        if anti:
            lines.append("## 禁止的写法（避免 AI 味）")
            lines.append("")
            for a in anti:
                if isinstance(a, dict):
                    a = str(a.get("pattern") or a.get("rule") or "").strip()
                if str(a).strip():
                    lines.append(f"- {str(a).strip()}")
            lines.append("")

        # 维度专属结构化字段（世界观/爽点/钩子/对话/动作/内心/描写/过渡）
        lines += DistillationEngine._render_special_fields(skill_data)

        # 人味统计指纹（13-15 轮产出：直击检测器统计信号）
        lines += DistillationEngine._render_human_signature(skill_data)

        # 旧格式兼容：老蒸馏数据（features/guidelines）没有 v2 字段时按旧结构展示
        if not moves and not soft and not hard and not anti:
            features = skill_data.get("features") or []
            if features:
                lines.append("## 风格特征")
                for f in features:
                    lines.append(f"- {f}")
                lines.append("")
            guidelines = skill_data.get("guidelines") or []
            if guidelines:
                lines.append("## 写作规则（生成时必须遵守）")
                for i, g in enumerate(guidelines, 1):
                    lines.append(f"{i}. {g}")
                lines.append("")
        return lines

    @staticmethod
    def _render_special_fields(skill_data: dict) -> list[str]:
        """渲染维度专属结构化字段（世界观/爽点/钩子/对话/动作/内心/描写/过渡）。

        这些字段来自专属模板的顶层 JSON key，直接对应该维度的 agent 执行诉求。
        """
        lines: list[str] = []
        for dim_key, (dim_name, fields) in _SPECIAL_FIELDS.items():
            present = [(k, v) for k, v in fields.items()
                       if skill_data.get(k) not in (None, "", [], {})]
            if not present:
                continue
            lines.append(f"## {dim_name}（结构化拆解）")
            lines.append("")
            for k, v in present:
                label = str(fields[k]).split("：", 1)[0]
                if isinstance(v, list):
                    lines.append(f"- **{label}**")
                    for item in v:
                        if str(item).strip():
                            lines.append(f"  - {str(item).strip()}")
                else:
                    lines.append(f"- **{label}**：{str(v).strip()}")
            lines.append("")
        return lines

    @staticmethod
    def _render_human_signature(skill_data: dict) -> list[str]:
        """渲染人味统计指纹块（rhythm_profile / ban_words / density_targets）。

        这些字段直接对应 AI 检测引擎的统计信号（burstiness/密度/连接词/重复词），
        渲染进 skill 正文后随注入链路进入写手 prompt，实现"检测与生成同指纹"。
        """
        rhythm = skill_data.get("rhythm_profile")
        ban_words = skill_data.get("ban_words")
        density = skill_data.get("density_targets")
        if not rhythm and not ban_words and not density:
            return []
        lines: list[str] = ["## 人味统计指纹（对齐 AI 检测器）", ""]

        if isinstance(rhythm, dict) and any(rhythm.values()):
            lines.append("### 节奏与句长分布")
            labels = {
                "short_sentence_ratio": "短句占比（15字内）",
                "long_sentence_ratio": "长句占比（40字以上）",
                "dialogue_ratio": "对话占比",
                "para_variation": "段落变化",
                "burstiness_note": "节奏手感",
            }
            for k, label in labels.items():
                v = rhythm.get(k)
                if v:
                    lines.append(f"- {label}：{v}")
            lines.append("")

        if ban_words:
            if isinstance(ban_words, str):
                ban_words = [ban_words]
            lines.append("### 禁词表（生成时避免）")
            for w in ban_words:
                if str(w).strip():
                    lines.append(f"- {str(w).strip()}")
            lines.append("")

        if isinstance(density, dict) and any(density.values()):
            lines.append("### 密度控制目标")
            labels = {
                "adj_density": "形容词密度",
                "dash_density": "破折号密度",
                "connector_density": "连接词密度",
                "repetition": "重复词控制",
            }
            for k, label in labels.items():
                v = density.get(k)
                if v:
                    lines.append(f"- {label}：{v}")
            lines.append("")
        return lines

    @staticmethod
    def _compose_condensed_content(level: int, data: dict, dim_name: str = "") -> str:
        """把浓缩 JSON 组装成可读的 markdown 总技能内容（格式 v2）。

        dim_name: 二级按维度分组时传入维度名（如"爽点设计"），标题中标注。
        dimension_index（三级说明书）：渲染在正文前，起到"说明书导览二级"的作用。
        """
        title = f"{dim_name} · " if dim_name else ""
        lines = [f"# {title}第{level}级蒸馏 · 写作风格总纲", ""]
        desc = str(data.get("description") or "").strip()
        if desc:
            lines += [desc, ""]
        # 三级说明书：维度索引（每个二级总纲对应哪个写作环节、何时翻）
        index = data.get("dimension_index")
        if index:
            lines += ["## 维度索引（写作时怎么用这套体系）", ""]
            for i, item in enumerate(index, 1):
                if isinstance(item, str):
                    lines.append(f"{i}. {item.strip()}")
                elif isinstance(item, dict):
                    dim = str(item.get("dimension") or "").strip()
                    stage = str(item.get("writing_stage") or "").strip()
                    how = str(item.get("how_to_use") or "").strip()
                    if dim:
                        line = f"{i}. **{dim}**"
                        if stage:
                            line += f"｜{stage}"
                        lines.append(line)
                        if how:
                            lines.append(f"   用法：{how}")
            lines.append("")
        lines += DistillationEngine._render_style_body(data)
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Skill 生成
    # ------------------------------------------------------------------
    def generate_skill(self, work_id: int, chunk_index: int, round_num: int) -> dict:
        """从蒸馏结果生成 Skill：写 DB 记录 + 写入项目 Skills 系统（JSON 文件）。"""
        work = self.store.get_work(work_id)
        if not work:
            raise ValueError(f"作品不存在: work_id={work_id}")
        chunk = self.store.get_chunk_by_index(work_id, chunk_index)
        if not chunk:
            raise ValueError(f"片段不存在: work_id={work_id} chunk_index={chunk_index}")
        round_row = self.store.get_round(chunk["id"], round_num)
        if not round_row or round_row["status"] != "done":
            raise ValueError(
                f"蒸馏轮次未完成: work_id={work_id} chunk_index={chunk_index} round={round_num}"
            )
        try:
            skill_data = json.loads(round_row["skill_data_json"])
        except (json.JSONDecodeError, TypeError):
            skill_data = {}
        dim_name = ROUND_DIMENSIONS.get(round_num, ("综合特征", ""))[0]
        display_name = skill_data.get("name") or f"{dim_name}"
        description = skill_data.get("description") or ""
        content = self._compose_skill_content(
            display_name, description, skill_data,
            work_title=work["title"], chunk_index=chunk_index,
            round_num=round_num, dim_name=dim_name,
        )
        # Skills 系统文件名只允许 [a-zA-Z0-9-_]，内部名用 ASCII，展示名存 description/name
        file_name = f"distill_w{work_id}_c{chunk_index}_r{round_num}"
        if (self._skills_dir() / f"{file_name}.json").exists():
            file_name = f"{file_name}_{uuid.uuid4().hex[:6]}"
        tags = skill_data.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        skill_id = self.store.create_skill(
            work_id=work_id, work_title=work["title"], chunk_index=chunk_index,
            round_num=round_num, name=file_name,
            description=f"【{display_name}】{description}" if description else f"【{display_name}】",
            content=content, tags=tags,
        )
        skill = self.store.get_skill(skill_id)
        # 文件 enabled 跟随 skill status（新建即 active → True）
        # 碎片是局部素材（一个片段×一个维度），归素材库型：写章时按上下文检索注入，
        # 不按 agent 定向过滤（写"战斗"要跨维度检索动作/环境/对话素材），故不打 agent_roles 标签。
        # 但写 dimension 维度号：检索时按当前 agent 的维度加权（同维度加分、跨维度不丢），
        # 只有定向注入的二级维度总纲/三级说明书才打 agent_roles 标签（见 _condense_group）。
        self._write_skill_file(file_name, display_name, description, content, tags,
                               status=skill.get("status", "active") if skill else "active",
                               category="material",
                               dimension=round_num)
        logger.info("Skill 已生成: id=%d name=%s (《%s》片段%d 第%d轮)",
                    skill_id, file_name, work["title"], chunk_index, round_num)
        return skill

    @staticmethod
    def _compose_skill_content(display_name: str, description: str,
                               skill_data: dict, work_title: str,
                               chunk_index: int, round_num: int,
                               dim_name: str) -> str:
        """把蒸馏结果组合为 Skill 正文（markdown，格式 v2）。"""
        lines = [f"# {display_name}", ""]
        if description:
            lines += [description, ""]
        lines += DistillationEngine._render_style_body(skill_data)
        lines.append("## 溯源")
        lines.append(f"- 来源作品：《{work_title}》第 {chunk_index + 1} 片段")
        lines.append(f"- 蒸馏轮次：第 {round_num} 轮（{dim_name}）")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Skills 系统文件（project_data/skills/*.json）
    # ------------------------------------------------------------------
    @staticmethod
    def _skills_dir() -> Path:
        cfg = load_config()
        d = cfg.project_data_dir / "skills"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_skill_file(self, file_name: str, display_name: str,
                          description: str, content: str,
                          tags: list[str] | None = None,
                          status: str = "active",
                          category: str = "rule",
                          agent_roles: list[str] | None = None,
                          dimension: int | None = None) -> Path:
        """按 routes_skills 的 JSON 格式写入 Skills 系统，供生成流程加载。

        enabled 跟随 skill 状态：active → True，archived → False。
        注入侧（routes_skills.load_enabled_skills_for_injection*）会跳过
        enabled=False 的 skill，因此归档/禁用的 skill 不再注入生成流程。

        category：rule=规则型（全量注入）/ material=素材库型（按上下文检索注入）。
        蒸馏碎片传 material（量大且重复，只能按需检索），总纲/融合传 rule。

        agent_roles：该 skill 适用的 agent 列表（蒸馏维度→agent 映射）。
        注入侧按当前 agent_type 过滤：有 agent_roles 且不含当前 agent 的 skill 跳过，
        实现"每个 agent 只看自己负责维度的总纲"，避免全量注入撑爆上下文。
        素材库碎片不传（空=通用不过滤，写"战斗"可跨维度检索动作/环境/对话素材）。

        dimension：蒸馏维度号（1-19），碎片写入供检索侧加权——当前 agent 负责的
        维度命中时检索加分（同维度素材排前），但不过滤跨维度素材。
        """
        path = self._skills_dir() / f"{file_name}.json"
        data = {
            "name": file_name,
            "description": f"【{display_name}】{description}" if description else f"【{display_name}】",
            "enabled": status != "archived",
            "auto_inject": True,
            "category": category,
            "sections": [{"name": "distilled_style", "content": content}],
            "tools": [],
            "references": [],
            "distilled": True,
            "tags": tags or [],
            "agent_roles": agent_roles or [],
            "dimension": dimension,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    # ------------------------------------------------------------------
    # 融合
    # ------------------------------------------------------------------
    async def fuse_skills(self, skill_ids: list[int], weights: list[float] | None,
                          fusion_name: str, description: str = "",
                          client: LLMClient | None = None,
                          on_event: OnEvent | None = None,
                          extra_skills: list[dict] | None = None) -> dict:
        """提炼式融合多个 Skill（支持"九合一"等模式）。

        有 client 时：把多个 Skill 交给 LLM 浓缩提炼成一份精炼总纲（非简单拼接）——
        分批 → 每批提炼 → 递归归并 → 输出 v2 结构化总纲；高权重来源优先保留。
        无 client 或提炼失败时：回退为按权重降序拼接（保底，不阻塞功能）。

        extra_skills: 不在蒸馏 DB 中的 Skill（如拆书 skill），以 dict（含 content /
            work_title / chunk_index / round_num）传入，与 DB skill 一起参与融合。

        融合产物：
        - distill_fusions 表记录（skill_ids + weights，仅 DB skill）
        - Skills 系统写入融合 Skill 文件 distill_fusion_{fusion_id}.json

        Returns:
            {"fusion_id": int, "skill_file": str, "skill_count": int, "refined": bool}
        """
        if not skill_ids and not extra_skills:
            raise ValueError("skill_ids 不能为空")
        skills = []
        for sid in skill_ids:
            skill = self.store.get_skill(sid)
            if not skill:
                raise ValueError(f"Skill 不存在: id={sid}")
            skills.append(skill)
        if extra_skills:
            skills = skills + [dict(s) for s in extra_skills]
        if weights and len(weights) == len(skills):
            w = [max(0.0, float(x)) for x in weights]
        else:
            w = [1.0] * len(skills)
        total = sum(w) or 1.0
        w = [x / total for x in w]

        fusion_id = self.store.create_fusion(
            name=fusion_name, skill_ids=skill_ids, weights=w,
            description=description,
        )

        ordered = sorted(zip(skills, w), key=lambda x: x[1], reverse=True)

        # 有 LLM：提炼式融合
        refined = False
        content = None
        if client is not None:
            blocks = []
            for skill, weight in ordered:
                ci, rn = skill.get("chunk_index", -1), skill.get("round_num", 0)
                chunk_info = f"片段{ci + 1} 第{rn}轮" if ci >= 0 else ""
                body = (skill.get("content") or "").strip()
                if not body:
                    continue
                blocks.append(f"【来源：《{skill.get('work_title', '')}》{chunk_info} · 权重 {weight:.0%}】\n{body}")
            if blocks:
                try:
                    final_text = await self._fuse_all(blocks, client, on_event)
                    if final_text is None:
                        raise RuntimeError("LLM 融合提炼失败（所有批次均失败）")
                    parsed = parse_json_safe(final_text)
                    if isinstance(parsed, dict) and parsed:
                        content = self._compose_fusion_content(fusion_name, description, parsed)
                        refined = True
                    elif final_text and final_text.strip():
                        content = final_text.strip()
                except Exception as e:
                    logger.warning("融合提炼失败（fusion_id=%d），回退为按权重拼接: %s", fusion_id, e)

        # 无 client / 提炼失败：回退为按权重降序拼接
        if content is None:
            lines = [f"# 融合写作风格：{fusion_name}", ""]
            if description:
                lines += [description, ""]
            lines += [f"本 Skill 由 {len(skills)} 个蒸馏 Skill 按权重融合而成（提炼失败，已回退拼接）。", ""]
            for skill, weight in ordered:
                lines.append("---")
                ci, rn = skill.get("chunk_index", -1), skill.get("round_num", 0)
                chunk_info = f"片段{ci + 1} 第{rn}轮" if ci >= 0 else ""
                lines.append(f"## 来源：《{skill.get('work_title', '')}》{chunk_info}（权重 {weight:.0%}）")
                lines.append("")
                lines.append(skill.get("content") or "")
                lines.append("")
            content = "\n".join(lines)

        file_name = f"distill_fusion_{fusion_id}"
        if (self._skills_dir() / f"{file_name}.json").exists():
            file_name = f"{file_name}_{uuid.uuid4().hex[:6]}"
        tags = ["融合", f"{len(skills)}合一"] + (["AI提炼"] if refined else [])
        self._write_skill_file(
            file_name, fusion_name,
            description or f"{len(skills)} 个蒸馏 Skill 的加权融合",
            content, tags=tags,
        )
        logger.info("Skill 融合完成: fusion_id=%d name=%s (%d 个 Skill, refined=%s)",
                    fusion_id, fusion_name, len(skills), refined)
        return {
            "fusion_id": fusion_id,
            "skill_file": file_name,
            "skill_count": len(skills),
            "refined": refined,
        }

    async def _fuse_all(self, blocks: list[str], client: LLMClient,
                        on_event: OnEvent | None = None) -> str | None:
        """递归分批融合：块数过多时先分批提炼为子总纲，再融合子总纲。

        skill 数量不限（如"全选 282 个"也直接跑）：超出 _FUSE_MAX_BLOCKS 时
        按序切批，**各批并行提炼**（并发数 _FUSE_CONCURRENCY，受 LLM API 限流约束），
        再递归融合子总纲，直到剩下 1 份。
        任一批提炼失败不阻断整体：该批以原始拼接文本保底，继续参与上层融合；
        所有批次都无法提炼时返回 None（由调用方走明确标注的回退路径）。
        """
        if len(blocks) <= self._FUSE_MAX_BLOCKS:
            return await self._fuse_to_one(blocks, client, on_event)
        total_batches = (len(blocks) + self._FUSE_MAX_BLOCKS - 1) // self._FUSE_MAX_BLOCKS
        sem = asyncio.Semaphore(self._FUSE_CONCURRENCY)

        async def _process(start: int) -> str:
            batch = blocks[start:start + self._FUSE_MAX_BLOCKS]
            batch_no = start // self._FUSE_MAX_BLOCKS + 1
            await self._emit(on_event, {
                "type": "fuse_sub_batch_start", "batch": batch_no,
                "total": total_batches, "count": len(batch),
            })
            async with sem:  # 限流：最多 _FUSE_CONCURRENCY 批同时调 LLM
                try:
                    text = await self._fuse_to_one(batch, client, on_event)
                except Exception as e:
                    logger.warning("融合子批 %d/%d 提炼异常，回退为该批拼接: %s",
                                   batch_no, total_batches, e)
                    text = None
            if text:
                result = text
            else:
                # 该批提炼失败：以原始拼接保底参与上层融合（不静默丢弃）
                logger.warning("融合子批 %d/%d 提炼失败，以原始内容保底", batch_no, total_batches)
                result = "\n\n".join(batch)
            await self._emit(on_event, {
                "type": "fuse_sub_batch_done", "batch": batch_no, "total": total_batches,
            })
            return result

        # 并行提炼所有子批；asyncio.gather 保持输入顺序，归并顺序稳定
        sub_blocks = await asyncio.gather(*(
            _process(start) for start in range(0, len(blocks), self._FUSE_MAX_BLOCKS)
        ))
        return await self._fuse_all(list(sub_blocks), client, on_event)

    async def _fuse_to_one(self, blocks: list[str], client: LLMClient,
                           on_event: OnEvent | None = None) -> str:
        """多 Skill 融合提炼：分批 → 每批 LLM 提炼 → 递归归并直到剩 1 块。"""
        safety = 0
        while len(blocks) > 1 and safety < 12:
            safety += 1
            batches = self._batch_texts(blocks, budget=self._CONDENSE_BATCH_BUDGET)
            new_blocks: list[str] = []
            for i, batch in enumerate(batches):
                if len(batches) > 1:
                    await self._emit(on_event, {
                        "type": "fuse_batch_start", "batch": i + 1, "total": len(batches),
                    })
                try:
                    text = await self._llm_fusion(batch, client)
                    if text and text.strip():
                        new_blocks.append(text.strip())
                except Exception as e:
                    logger.warning("融合批 %d/%d 失败: %s", i + 1, len(batches), e)
                if len(batches) > 1:
                    await self._emit(on_event, {
                        "type": "fuse_batch_done", "batch": i + 1, "total": len(batches),
                    })
            blocks = new_blocks if new_blocks else ["\n\n".join(blocks)]
        if len(blocks) == 1 and blocks[0] and blocks[0].count("【来源：") <= 1:
            return blocks[0]
        return None

    async def _llm_fusion(self, batch_texts: list[str], client: LLMClient) -> str:
        """单批融合提炼：LLM 把多个 Skill 浓缩成精炼总纲（权重越高越优先保留）。"""
        user = (
            f"【多 Skill 融合 · 提炼浓缩】\n"
            f"下面是 {len(batch_texts)} 个写作 Skill 的内容，每个开头标注了来源权重"
            f"（权重越高越重要）。请融合提炼成一份精炼总纲：\n"
            f"- 合并重复项，去粗取精，只保留共性规律与可操作规则；\n"
            f"- 高权重的 Skill 的规则优先保留；低权重且与高权重冲突的规则让位或舍弃；\n"
            f"- 不要照抄原文，用自己的话概括；输入越多，压缩得越狠。\n\n"
            + "\n\n---\n\n".join(batch_texts)
            + "\n\n" + _CONDENSE_OUTPUT_SPEC
        )
        return await client.generate(user, system=_CONDENSE_SYSTEM, node_name="distill_fuse",
                                     thinking=False)

    @staticmethod
    def _compose_fusion_content(fusion_name: str, description: str, data: dict) -> str:
        """把融合提炼的 v2 JSON 组装成融合 Skill 正文（markdown）。"""
        lines = [f"# 融合写作风格：{fusion_name}", ""]
        desc = str(data.get("description") or description or "").strip()
        if desc:
            lines += [desc, ""]
        lines += DistillationEngine._render_style_body(data)
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # 效果对比
    # ------------------------------------------------------------------
    async def compare_generate(self, prompt: str, client: LLMClient,
                               skill_id: int | None = None) -> dict:
        """对比"无章纲直出" vs "加载蒸馏 Skill 直出"。

        Returns:
            {"baseline": str, "with_skill": str | None, "skill": dict | None}
        """
        baseline = await client.generate(
            prompt, system=_COMPARE_BASE_SYSTEM, node_name="distill_compare",
        )
        with_skill: str | None = None
        skill: dict | None = None
        if skill_id is not None:
            skill = self.store.get_skill(skill_id)
            if not skill:
                raise ValueError(f"Skill 不存在: id={skill_id}")
            system = (
                f"{_COMPARE_BASE_SYSTEM}\n\n"
                f"【写作风格要求】\n请严格模仿以下蒸馏出的写作风格：\n\n{skill['content']}"
            )
            with_skill = await client.generate(
                prompt, system=system, node_name="distill_compare",
            )
        return {"baseline": baseline, "with_skill": with_skill, "skill": skill}

    # ------------------------------------------------------------------
    # 人物级蒸馏（参考造梦.skill）
    # ------------------------------------------------------------------

    _CHARACTER_DISTILL_PROMPT = """你是一位资深的人物对话风格分析专家。请从以下小说文本中，提取角色「{character}」的说话风格特征。

## 角色名
{character}

## 小说文本片段
{content}

## 输出要求
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{{
  "name": "角色说话风格（≤12字，如「冷峻短句型」）",
  "description": "一句话概括这个角色的对话风格",
  "features": [
    "具体特征，每条附原文对话例证。例如：句式极短，多用陈述句，不使用语气词",
    "用词偏好：经常使用哪些词，回避哪些词",
    "语气节奏：语速快/慢，停顿多/少",
    "情感表达：直接/含蓄，口头禅",
    "...",
  ],
  "guidelines": [
    "可执行的对话写作规则。例如：写这个角色的对话时，每句不超过15字",
    "不使用「啊」「呢」「嘛」等语气词",
    "面对威胁时语气更冷，句子更短",
    "...",
  ],
  "tags": ["角色标签", "风格标签"],
  "sample_lines": ["从原文中摘录3-5句最能代表该角色风格的对话原文"],
}}

其中 features 5-10 条，guidelines 5-10 条，tags 2-5 个，sample_lines 3-5 条。
注意：如果文本中该角色的对话不足3句，在 description 中说明「对话样本不足」，features 和 guidelines 尽量基于有限样本提取。"""

    async def distill_character(
        self,
        work_id: int,
        character_name: str,
        client: LLMClient,
        on_event: OnEvent | None = None,
    ) -> dict:
        """从作品中蒸馏单个角色的对话风格。

        遍历所有片段，提取包含该角色的段落，合并后让 LLM 分析说话风格。
        生成一个 character-style skill，供生成对话时注入。

        Returns:
            {"skill_id": int, "skill_name": str, "character": str, "content": str}
        """
        work = self.store.get_work(work_id)
        if not work:
            raise ValueError(f"作品不存在: work_id={work_id}")

        chunks = self.store.list_chunks(work_id, include_content=True)
        if not chunks:
            raise ValueError(f"作品无片段: work_id={work_id}")

        # 筛选包含角色名的片段，合并（最多 5 万字）
        char_parts: list[str] = []
        total_chars = 0
        for chunk in chunks:
            content = chunk.get("content", "")
            if character_name in content:
                char_parts.append(content)
                total_chars += len(content)
                if total_chars >= 50000:
                    break

        if not char_parts:
            raise ValueError(f"在作品中未找到角色「{character_name}」的出场段落")

        merged = "\n\n---\n\n".join(char_parts)[:50000]

        await self._emit(on_event, {
            "type": "character_distill_start",
            "character": character_name,
            "sample_chars": len(merged),
        })

        prompt = self._CHARACTER_DISTILL_PROMPT.format(
            character=character_name, content=merged,
        )

        try:
            result_text = await client.generate(
                prompt, system=_DISTILL_SYSTEM, node_name="distill_character",
            )
        except Exception as e:
            await self._emit(on_event, {
                "type": "character_distill_failed",
                "character": character_name, "error": str(e),
            })
            raise

        skill_data = parse_json_safe(result_text)
        if skill_data is None:
            logger.warning("角色蒸馏 JSON 解析失败 (%s)，使用兜底结构", character_name)
            skill_data = {
                "name": f"{character_name}对话风格",
                "description": "（LLM 输出未按 JSON 格式返回，已保留原始分析文本）",
                "features": [],
                "guidelines": [result_text.strip()[:500]],
                "tags": [character_name, "角色风格"],
                "sample_lines": [],
            }

        # 组装 skill 内容
        display_name = skill_data.get("name") or f"{character_name}对话风格"
        description = skill_data.get("description") or ""
        features = skill_data.get("features") or []
        guidelines = skill_data.get("guidelines") or []
        tags = skill_data.get("tags") or [character_name]
        sample_lines = skill_data.get("sample_lines") or []

        lines = [f"# {display_name}", ""]
        if description:
            lines += [description, ""]
        if sample_lines:
            lines.append("## 原文对话样本")
            for sl in sample_lines:
                lines.append(f"> {sl}")
            lines.append("")
        if features:
            lines.append("## 说话风格特征")
            for f in features:
                lines.append(f"- {f}")
            lines.append("")
        if guidelines:
            lines.append("## 对话写作规则（生成该角色对话时必须遵守）")
            for i, g in enumerate(guidelines, 1):
                lines.append(f"{i}. {g}")
            lines.append("")
        lines.append("## 溯源")
        lines.append(f"- 来源作品：《{work['title']}》")
        lines.append(f"- 蒸馏角色：{character_name}")
        content = "\n".join(lines)

        # 写入 Skills 系统（文件名过滤 Windows 非法字符，避免中文/特殊字符角色名导致 OSError）
        file_name = f"distill_char_{work_id}_{character_name}"
        safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", file_name).replace(" ", "_")[:80] or "distill_char"
        self._write_skill_file(
            safe_name, display_name,
            f"角色对话风格·{character_name}（来源：《{work['title']}》）",
            content, tags=tags + ["角色蒸馏"],
        )

        # 也写入 DB（作为特殊 round_num=99 标记角色蒸馏）
        skill_id = self.store.create_skill(
            work_id=work_id, work_title=work["title"],
            chunk_index=-1, round_num=99,
            name=safe_name,
            description=f"【{display_name}】{character_name}的对话风格",
            content=content, tags=tags + ["角色蒸馏"],
        )

        await self._emit(on_event, {
            "type": "character_distill_done",
            "character": character_name,
            "skill_id": skill_id,
            "skill_name": safe_name,
        })

        skill = self.store.get_skill(skill_id)
        return {
            "skill_id": skill_id,
            "skill_name": safe_name,
            "character": character_name,
            "content": content,
            "skill": skill,
        }

    # ------------------------------------------------------------------
    # 盲测评估（参考 writer-style-skill-factory）
    # ------------------------------------------------------------------

    _BLIND_JUDGE_PROMPT = """你是一位专业的文学编辑。下面有两段AI生成的小说片段（标记为A和B），它们基于同一个写作要求生成。
其中一段使用了从原作中蒸馏出的写作风格Skill，另一段没有使用。
请你判断哪一段更接近原作的风格，并给出评分。

## 原作风格参考
{skill_content}

## 写作要求
{prompt}

## 片段A
{text_a}

## 片段B
{text_b}

## 输出要求
只输出一个 JSON 对象（不要输出任何其他文字），格式：
{{
  "winner": "A" 或 "B" 或 "tie",
  "confidence": 0.0-1.0,
  "score_a": 1-10,
  "score_b": 1-10,
  "reason": "判断理由（≤100字）",
  "style_match_a": "A段与原作风格的匹配度评价（≤50字）",
  "style_match_b": "B段与原作风格的匹配度评价（≤50字）"
}}"""

    async def blind_evaluate(
        self,
        skill_id: int,
        prompt: str,
        client: LLMClient,
    ) -> dict:
        """对蒸馏 skill 做盲测评估。

        流程：
        1. 用 skill 生成一段文字（with_style）
        2. 不用 skill 生成一段文字（baseline）
        3. 随机打乱顺序，让 LLM 盲评哪段更接近原作风格
        4. 返回评估结果

        Returns:
            {"baseline": str, "with_style": str, "judgment": dict}
        """
        import random

        skill = self.store.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill 不存在: id={skill_id}")

        # 1. 生成两段文字
        baseline = await client.generate(
            prompt, system=_COMPARE_BASE_SYSTEM, node_name="distill_eval",
        )
        style_system = (
            f"{_COMPARE_BASE_SYSTEM}\n\n"
            f"【写作风格要求】\n请严格模仿以下蒸馏出的写作风格：\n\n{skill['content']}"
        )
        with_style = await client.generate(
            prompt, system=style_system, node_name="distill_eval",
        )

        # 2. 随机打乱顺序
        texts = [("baseline", baseline), ("with_style", with_style)]
        random.shuffle(texts)
        text_a_label, text_a = texts[0]
        text_b_label, text_b = texts[1]

        # 3. 盲评
        judge_prompt = self._BLIND_JUDGE_PROMPT.format(
            skill_content=skill["content"][:2000],
            prompt=prompt,
            text_a=text_a[:2000],
            text_b=text_b[:2000],
        )
        try:
            judge_text = await client.chat(
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0.1,
                max_tokens=1000,
            )
            judgment = parse_json_safe(judge_text.get("content", ""))
        except Exception as e:
            logger.warning("盲评 LLM 调用失败: %s", e)
            judgment = {"winner": "unknown", "reason": f"评估失败: {e}"}

        if judgment is None:
            judgment = {"winner": "unknown", "reason": "评估结果 JSON 解析失败"}

        # 还原标签
        judgment["text_a_is"] = text_a_label
        judgment["text_b_is"] = text_b_label
        if judgment.get("winner") == "A":
            judgment["winner_label"] = text_a_label
        elif judgment.get("winner") == "B":
            judgment["winner_label"] = text_b_label
        else:
            judgment["winner_label"] = "tie"

        return {
            "baseline": baseline,
            "with_style": with_style,
            "judgment": judgment,
            "skill": skill,
        }
