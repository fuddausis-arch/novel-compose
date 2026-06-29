"""LLM 完整 7 Gate 去 AI 味后处理器（移植 oh-story-claudecode story-deslop SKILL）。

完整实现 oh-story 体系：
- 7 Gate：A禁用词替换 / B句式去套路 / C心理外化 / D节奏打碎 / E对话去腔调 / F结尾去升华 / G去解释腔/上帝感/安排感
- 三遍法：Pass1去泛化 / Pass2去书面化 / Pass3回自然感
- 6项客观指标：禁用词密度/连续排比段数/心理词占比/对话标签密度/平均段落句数/重复描写密度
- AI味分级：轻度/中度/重度 → 对应 Pass 策略 + 删除比例上限
- 综合判定：取六项指标最高档位；任一指标达重度即按重度处理；无重度时中度指标≥3项按中度处理
- 删除比例上限：轻度≤15% / 中度≤25% / 重度≤35%

调用流程：
1. run_deslop_postprocess(text, llm_client) 入口
2. 先用 deslop_patterns 确定性检测，无 blocking 且 advisory≤2 时直接返回（节省 token）
3. score_ai_level(text) 计算 6 项客观指标，确定 AI 味等级
4. 按等级选择 Pass 策略，构建对应 prompt（含 7 Gate 规则子集）
5. 调用 LLM 改写，二次验证（不通过则回退原版本）

不修改 graph 主流程结构，由 polish_chapter / commit_chapter 节点按需注入。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from novel_agent.audit.deslop_patterns import run_deslop_checks

logger = logging.getLogger(__name__)

# ── AI 味等级常量 ──
LEVEL_MILD = "mild"        # 轻度：Pass1（去泛化，覆盖 Gate A/C/D/E/G）
LEVEL_MODERATE = "moderate"  # 中度：Pass1 + Pass2（+ Gate B 深化 + Gate A 书面腔）
LEVEL_SEVERE = "severe"    # 重度：完整三遍 + 重点段落重写

# ── 删除比例上限（百分比，0-1） ──
DELETE_RATIO_LIMIT = {
    LEVEL_MILD: 0.15,
    LEVEL_MODERATE: 0.25,
    LEVEL_SEVERE: 0.35,
}


# ════════════════════════════════════════════════════════════════════
# 第一部分：6 项客观指标 + AI 味分级
# ════════════════════════════════════════════════════════════════════

# 指标档位常量
_BAND_MILD = "mild"       # 轻度
_BAND_MODERATE = "moderate"  # 中度
_BAND_SEVERE = "severe"   # 重度


def _count_chinese(text: str) -> int:
    """统计中文字符数。"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def _count_banned_words(text: str, banned_list: list[str]) -> int:
    """统计文本中禁用词出现总次数。"""
    return sum(text.count(w) for w in banned_list)


# 6 项指标的核心检测词集（从 oh-story banned-words.md 提炼，与 deslop_patterns 保持一致）

# 心理词集（用于"心理词占比"指标）—— 告诉而非展示的硬信号
_PSYCHOLOGY_WORDS = [
    "心中一动", "心头一震", "心下了然", "心中暗道", "心底泛起", "不由得",
    "他感到", "她感到", "他意识到", "她意识到", "他知道", "她知道",
    "他明白", "她明白", "他终于明白", "她终于明白", "他这才意识到",
    "心中涌起", "心头涌起", "心里想着", "心想",
]

# 对话标签词（用于"对话标签密度"指标）
_DIALOG_TAG_WORDS = (
    "说道", "问道", "答道", "道：", "说：", "喊道", "笑道", "怒道",
    "冷道", "叹道", "低声道", "高声道", "轻声道", "缓缓说道",
)


def _metric_banned_density(text: str, banned_list: list[str]) -> dict:
    """指标1：禁用词密度（每千字禁用词出现次数）。

    档位：≤5 轻度 / 6-15 中度 / >15 重度
    """
    cn = _count_chinese(text) or 1
    hits = _count_banned_words(text, banned_list)
    density = hits / cn * 1000
    if density <= 5:
        band = _BAND_MILD
    elif density <= 15:
        band = _BAND_MODERATE
    else:
        band = _BAND_SEVERE
    return {
        "metric": "banned_density",
        "value": round(density, 1),
        "hits": hits,
        "band": band,
        "threshold": "≤5 mild / 6-15 moderate / >15 severe",
    }


def _metric_parallelism_runs(text: str) -> dict:
    """指标2：连续排比段数（相同句式连续出现段数）。

    档位：≤2 轻度 / 3-4 中度 / ≥5 重度

    检测：段首句式模板重复（"越来越X"/"放弃X"/"一边X一边Y"等）
    """
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paras) < 2:
        return {"metric": "parallelism_runs", "value": 0, "band": _BAND_MILD,
                "threshold": "≤2 mild / 3-4 moderate / ≥5 severe"}

    # 提取每段前 6 字作为模板指纹
    templates = []
    for p in paras:
        head = re.findall(r'[\u4e00-\u9fff]', p)[:6]
        templates.append("".join(head))

    max_run = 1
    cur_run = 1
    for i in range(1, len(templates)):
        # 模板相似度：前 3 字完全相同 或 模板完全相同
        # 前 3 字相同覆盖"越来越X""放弃X""他感到X"等典型排比模板
        if templates[i] and templates[i - 1] and (
            templates[i] == templates[i - 1]
            or templates[i][:3] == templates[i - 1][:3]
        ):
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1

    if max_run <= 2:
        band = _BAND_MILD
    elif max_run <= 4:
        band = _BAND_MODERATE
    else:
        band = _BAND_SEVERE
    return {
        "metric": "parallelism_runs",
        "value": max_run,
        "band": band,
        "threshold": "≤2 mild / 3-4 moderate / ≥5 severe",
    }


def _metric_psychology_ratio(text: str) -> dict:
    """指标3：心理词占比（心理类词字数 / 总字数）。

    档位：≤10% 轻度 / 10-25% 中度 / >25% 重度
    """
    cn = _count_chinese(text) or 1
    psycho_chars = sum(_count_chinese(w) * text.count(w) for w in _PSYCHOLOGY_WORDS)
    ratio = psycho_chars / cn
    if ratio <= 0.10:
        band = _BAND_MILD
    elif ratio <= 0.25:
        band = _BAND_MODERATE
    else:
        band = _BAND_SEVERE
    return {
        "metric": "psychology_ratio",
        "value": f"{ratio:.1%}",
        "band": band,
        "threshold": "≤10% mild / 10-25% moderate / >25% severe",
    }


def _metric_dialog_tag_density(text: str) -> dict:
    """指标4：对话标签密度（带标签对话句 / 全部对话句）。

    档位：≤30% 轻度 / 30-50% 中度 / >50% 重度
    """
    dial_sents = re.findall(r'[^\n。！？]*\u201c[^\u201d]*\u201d[^\n。！？]*[。！？]?', text)
    if not dial_sents:
        return {"metric": "dialog_tag_density", "value": "0%", "band": _BAND_MILD,
                "threshold": "≤30% mild / 30-50% moderate / >50% severe"}
    tagged = sum(1 for ds in dial_sents if any(t in ds for t in _DIALOG_TAG_WORDS))
    ratio = tagged / len(dial_sents)
    if ratio <= 0.30:
        band = _BAND_MILD
    elif ratio <= 0.50:
        band = _BAND_MODERATE
    else:
        band = _BAND_SEVERE
    return {
        "metric": "dialog_tag_density",
        "value": f"{ratio:.0%}",
        "band": band,
        "threshold": "≤30% mild / 30-50% moderate / >50% severe",
    }


def _metric_avg_paragraph_sentences(text: str) -> dict:
    """指标5：平均段落句数（每段平均句数，反映段落工整度）。

    档位：≤3 轻度 / 3-5 中度 / >5 重度（AI 工整感）

    注：网文以 1-3 句短段为主，平均句数过高=AI 工整段落。
    """
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paras) < 5:
        return {"metric": "avg_paragraph_sentences", "value": 0, "band": _BAND_MILD,
                "threshold": "≤3 mild / 3-5 moderate / >5 severe"}
    sent_counts = []
    for p in paras:
        sents = [s for s in re.split(r'[。！？]', p) if s.strip()]
        if sents:
            sent_counts.append(len(sents))
    if not sent_counts:
        return {"metric": "avg_paragraph_sentences", "value": 0, "band": _BAND_MILD,
                "threshold": "≤3 mild / 3-5 moderate / >5 severe"}
    avg = sum(sent_counts) / len(sent_counts)
    if avg <= 3:
        band = _BAND_MILD
    elif avg <= 5:
        band = _BAND_MODERATE
    else:
        band = _BAND_SEVERE
    return {
        "metric": "avg_paragraph_sentences",
        "value": round(avg, 2),
        "band": band,
        "threshold": "≤3 mild / 3-5 moderate / >5 severe",
    }


def _metric_repetition_density(text: str) -> dict:
    """指标6：重复描写密度（每千字重复描写处数）。

    档位：≤1 轻度 / 2-3 中度 / ≥4 重度

    检测：相同身体动作/情绪描写在千字内重复出现
    """
    cn = _count_chinese(text) or 1
    # 重复描写的特征词（身体动作+情绪模板）
    repeat_templates = [
        "深吸一口气", "瞳孔", "嘴角", "后背", "心跳", "汗毛",
        "眼中闪过", "心头", "心中", "脸色", "眼神",
    ]
    repetition_count = 0
    for tpl in repeat_templates:
        c = text.count(tpl)
        if c >= 2:
            repetition_count += c - 1  # 第一次不算重复
    density = repetition_count / cn * 1000
    if density <= 1:
        band = _BAND_MILD
    elif density <= 3:
        band = _BAND_MODERATE
    else:
        band = _BAND_SEVERE
    return {
        "metric": "repetition_density",
        "value": round(density, 2),
        "band": band,
        "threshold": "≤1 mild / 2-3 moderate / ≥4 severe",
    }


# 档位到等级的优先级映射
_BAND_PRIORITY = {_BAND_MILD: 0, _BAND_MODERATE: 1, _BAND_SEVERE: 2}


def score_ai_level(text: str, banned_list: list[str] | None = None) -> dict:
    """计算 6 项客观指标，返回 AI 味等级（轻度/中度/重度）。

    综合判定规则（来自 oh-story SKILL.md）：
    - 取六项指标最高档位
    - 任一指标达重度即按重度处理
    - 无重度时中度指标≥3项按中度处理
    - 否则按轻度处理

    返回：{
        "level": "mild"/"moderate"/"severe",
        "metrics": [6项指标详情],
        "moderate_count": N,
        "severe_count": N,
    }
    """
    if banned_list is None:
        # 从 validator 加载禁用词清单
        try:
            from novel_agent.audit.validator import _load_forbidden_words
            banned_list = [r["word"] for r in _load_forbidden_words()]
        except Exception:
            banned_list = []

    metrics = [
        _metric_banned_density(text, banned_list),
        _metric_parallelism_runs(text),
        _metric_psychology_ratio(text),
        _metric_dialog_tag_density(text),
        _metric_avg_paragraph_sentences(text),
        _metric_repetition_density(text),
    ]

    severe_count = sum(1 for m in metrics if m["band"] == _BAND_SEVERE)
    moderate_count = sum(1 for m in metrics if m["band"] == _BAND_MODERATE)

    if severe_count >= 1:
        level = LEVEL_SEVERE
    elif moderate_count >= 3:
        level = LEVEL_MODERATE
    else:
        level = LEVEL_MILD

    return {
        "level": level,
        "metrics": metrics,
        "moderate_count": moderate_count,
        "severe_count": severe_count,
    }


# ════════════════════════════════════════════════════════════════════
# 第二部分：完整 7 Gate 规则集 + 三遍法 Prompt 构建
# ════════════════════════════════════════════════════════════════════

# ── Gate A：禁用词替换 ──
GATE_A_RULES = """【Gate A：禁用词替换】
最毒句式（命中即修）：
- "不是A，(而)是B" / "不是A，不是B，(而)是C" → 直接写 B 或更自然的表达
- "，带着……" 万能状语 → 拆短句或换动作
- "声音不大，却带着一种……的力量" → 直接写声音特征或动作
- "他/她知道……" → 用行为展示认知
- "他不知道的是……" → 用具体钩子物件/事件收束，避免空泛预告
- "仿佛/犹如/宛若……一般" → 删掉或白描
- "眼中闪过一丝……" / "嘴角勾起一抹……" → 用"垂下眼"/"笑了一下，没到眼底"替代
- "心中涌起一股……" / "心头一震" → 用身体反应

一级禁用词（出现即替换）：
- 情态类：仿佛、犹如、宛若、如同、一丝、一抹、些许、几分、隐约
- 动作类：深吸一口气、缓缓、不禁、微微、轻轻、淡淡
- 表情类：眼中闪过、嘴角勾起、眉头微皱、眉眼低垂、瞳孔微缩
- 心理类：心中一动、心头一震、心下了然、心中暗道、心底泛起、不由得
- 判断类：不容置疑、不容置喙、不易察觉、显而易见、毫无疑问、不可否认
- 形容类：坚定、闪烁着光芒、狡黠、深邃、凛冽、冰冷
- 过渡类：不由自主、情不自禁、自然而然

二级禁用词（高频时替换）：
- 书面腔"瓦解"→消失/散了/没了；"无名火"→烦躁；"往我心上捅刀子"→心烦意乱
- 总结句式"他/她终于明白..."/"他/她这才意识到..."/"此刻，他/她..."/"一切...都..."/"原来..."
- 排比句式"有的...有的...有的..."/"一边...一边...一边..."
- 升华句式"这一刻..."/"他知道..."/"她明白..."/"这就是..."
"""

# ── Gate B：句式去套路 ──
GATE_B_RULES = """【Gate B：句式去套路】
连续排比段数 ≥3 必须打散：
- 连续 3 句以上相同结构的排比，只保留最强一条
- "越来越X越来越Y越来越Z" → 最多保留 2 个
- "放弃X！放弃Y！放弃Z！" → 最多保留 2 个
- "有的...有的...有的..." → 删掉，改具体描写
- "一边...一边...一边..." → 拆成独立动作句

句式模板化（≥3 处即修）：
- "他/她XX地+动词"（"他缓慢地走"/"她轻轻地笑"）→ 删副词，用动作本身
- "X的Y，Z的W"对仗工整句 → 拆成自然短句
- "不仅X，更是Y" 递进堆砌 → 删一个，保留直接表达
"""

# ── Gate C：心理外化（含重复描写去重） ──
# 对齐 oh-story SKILL.md:241-278（补重复描写去重 + 重复语义四类 + 多余场景删除）
GATE_C_RULES = """【Gate C：心理外化（"告诉"改"展示"）+ 重复描写去重】
心理词占比 >10% 必须外化：
- "他感到愤怒" → "攥紧拳头""青筋暴起"
- "她感到恐惧" → "退后一步""呼吸急促"
- "他意识到事情不对" → 直接写他做了什么反应
- "她终于明白了" → 删掉，让动作/对话体现认知
- "心中涌起一股暖流" → 写具体身体反应"胸口热了一下"
- "心头一震" → "手抖了一下""愣了半秒"

重复描写去重（合并同一瞬间）：
- 同一瞬间被拆成多段描写的（如先写眼神再写嘴角再写呼吸），合并成 1-2 句动作链
- 同一动作/情绪在千字内重复 2 次以上的，第 2 次起删掉或换不同身体反应

重复语义四类必须去重：
- 形容词重复："冰冷的目光""冰冷的声音" → 保留一个，另一个换具体描写
- 近义词重复："愤怒""暴怒""怒火" 同段出现 → 只留最强一个
- 含义重复："他笑了""他露出笑容" → 删一个
- 上下文主语重复：连续多段以"他"开头 → 改换视角或省略主语

多余场景/人物/物品描写直接删：
- 与当前剧情无关的环境描写（出场后不再用到的道具/路人）
- 重复交代已建立的人物外貌/穿着
- 不推动剧情的内心独白段落

铁律：能用动作/对话/身体反应展示的，禁止直接告诉读者情绪名词。
"""

# ── Gate D：节奏打碎（含标点节奏） ──
# 对齐 oh-story SKILL.md:280-288（补标点节奏 + 偶尔用不完整句）
GATE_D_RULES = """【Gate D：节奏打碎（拆长段+插短句+标点节奏）】
长段落（>200 字）必须拆成 1-3 句短段。
平均段落句数 >5 必须打散——网文以 1-3 句短段为主。

句号结巴（连续 ≥4 个 ≤6 字短句）也要修：
- 偶尔短句轰炸是力量，连续短句轰炸是机械感
- 在连续短句中插入一个稍长句（10-15 字）做呼吸

排比段（相同句式段连续 ≥3）必须打散：
- 第 1 段保留，第 2 段改写句式，第 3 段换角度或删

偶尔用不完整句增加口语感：
- 关键反应可单独成段（"试过了。""确实打不过。""什么？！"）
- 但不要连续 4 个以上不完整句，否则变机械感

标点节奏跟语气走：
- 保留问号？增强悬念
- 保留少量感叹号！增强冲击（每千字不超过 2-3 个）
- 省略号……改逗号或句号（除非真的表示话未说完被截断）
- 破折号——一律改逗号/句号/换行（机械兜底会再清一次）
"""

# ── Gate E：对话去腔调（补 5 项规则） ──
# 对齐 oh-story SKILL.md:290-299（补口语化/打断/动作穿插/删解释性/保留？！）
GATE_E_RULES = """【Gate E：对话去腔调】
对话标签密度 >30% 必须精简：
- 连续对话靠语气区分角色，删掉多余提示语
- "他微笑着说""她温柔地开口" → 后置或省略
- 普通"说"可保留，但"说道/问道/答道"高频时改用动作
- "道：" / "说：" 模板化标签 → 删一半，用动作替代

对话内容腔调 5 项：
1. 加口语化：适当插入"嗯/哦/行吧/得了/算了"等语气词，让台词像真人说的
2. 适当打断对话：角色可以答非所问、被动作截断、半句话被打断
3. 用动作穿插对话：连续对白间插入人物动作（点烟/站起来/看向窗外），打破纯对话堆砌
4. 删解释性对话：角色不会把内心动机直接说出来解释给对方听（除非角色性格就是话痨）
5. 不把所有对话末尾改句号：保留问号？/感叹号！/省略号的自然语气，不要为了"规范"全改句号

AI 角色台词太书面化时，改口语（"我无法继续" → "我写不下去了"）。
但系统流题材 AI 角色机械感台词是合法的，豁免。
"""

# ── Gate F：结尾去升华 ──
GATE_F_RULES = """【Gate F：结尾去升华】
章末段落禁止升华句式：
- "这一刻，他终于明白了……" → 删
- "他知道，这一切都……" → 删
- "她明白，原来……" → 删
- "这就是……的意义" → 删
- "或许，也许，大概……" → 删

章末应该是：
- 具体钩子物件/事件收束（一封信、一个电话、一个动作）
- 突然中断（动作未完成、对话被打断）
- 不要总结感慨，不要空泛预告"他不知道的是，更大的风暴即将来临"
"""

# ── Gate G：去解释腔/上帝感/安排感（补替读者定性 + 隐蔽软评判） ──
# 对齐 oh-story SKILL.md:310-319（补之所以/原来 + 替读者定性 + 隐蔽软评判 + 注意事项）
GATE_G_RULES = """【Gate G：去解释腔/上帝感/安排感】
解释腔（作者跳出来解释）：
- "也就是说……" / "换句话说……" → 删
- "这意味着……" / "这预示着……" → 删
- "事实上……" / "实际上……" → 删（除非对话角色口语）
- "之所以……是因为……" → 删因果解释，让事件自己呈现
- "原来……" → 删（除非是对话角色恍然大悟的台词）

上帝感（全知视角剧透）：
- "他不知道的是……" → 删（限知视角铁律）
- "此时的他还不知道……" → 删
- "殊不知……" → 删
- "多年以后……" → 删（除非是刻意倒叙结构）
- "仿佛预示着……" → 删
- "命运齿轮开始转动" → 删
- "更大的风暴即将来临" → 删

替读者定性（最难察觉的 AI 味，作者替读者下判断）：
- "演得真好" / "这出戏她看过一遍" → 删，让读者自己感受
- "他就是这样薄情" / "她就是这样的人" → 删定性，用具体行为展示

隐蔽软评判（伪装成细节的作者评判）：
- "关切得恰到好处" → 删"恰到好处"的评判
- "那点笑她看得分明" → 删"看得分明"的全知感
- "像在宣判一件早已定好的事" → 删"早已定好"的宿命感

安排感（剧情推进过于刻意）：
- "就在这时" / "恰在此时" 高频时改用具体动作过渡
- "果不其然" / "不出所料" → 删，让事件自己发生
- "这正是个好机会" → 删心理活动，用动作体现

注意：Gate G 删的是"非故事性作者旁白"——不要删情节本身。
如果某句是角色台词或推动剧情的叙述，保留；只删作者跳出来评论/剧透/定性的部分。
"""


# ── 三遍法：每遍的 Gate 覆盖关系 ──
# Pass1 去泛化：覆盖 Gate A / C / D / E / G
# Pass2 去书面化：覆盖 Gate A 书面腔 / Gate B 深化
# Pass3 回自然感：覆盖 Gate D / E / F + 补具体感官细节

PASS1_GATES = GATE_A_RULES + "\n" + GATE_C_RULES + "\n" + GATE_D_RULES + "\n" + GATE_E_RULES + "\n" + GATE_G_RULES
PASS2_GATES = GATE_A_RULES + "\n" + GATE_B_RULES
# Pass3 末尾追加"补具体感官细节"规则（对齐 oh-story SKILL.md:146）
PASS3_GATES = GATE_D_RULES + "\n" + GATE_E_RULES + "\n" + GATE_F_RULES + """

【Pass3 专属：补具体感官细节】
去AI味后文本可能变干瘪，需补回具体感官细节让画面立体：
- 视觉：颜色/形状/光影（"红色的锈迹""斜斜的光柱"）
- 听觉：声音特征（"金属撞击的脆响""布料摩擦的窸窣"）
- 触觉：温度/质感（"掌心发烫""粗糙的水泥地"）
- 嗅觉：气味（"机油味""血腥味""潮湿的霉味"）
- 每千字补 2-3 处感官细节，不要堆砌（每段最多 1 处）
- 感官细节必须绑定人物动作或感知，禁止独立抒情段落
"""


def _build_pass_prompt(pass_name: str, gates_rules: str, text: str,
                      delete_ratio_limit: float, ai_level: str,
                      metrics_summary: str) -> str:
    """构建单遍 Pass 的 LLM prompt。"""
    return f"""你是去AI味编辑，执行 {pass_name}。

当前文本 AI 味等级：{ai_level}
本遍允许删除比例上限：{delete_ratio_limit:.0%}

【本遍执行的 Gate 规则】
{gates_rules}

【6项客观指标诊断】
{metrics_summary}

【改写铁律——不得违反】
1. 不得改变剧情、设定、伏笔、角色关系。只改文字表达，不改故事内容。
2. 不得增删角色台词含义，只可调整措辞。
3. 不得新增角色、场景、道具。
4. 删除比例不得超过 {delete_ratio_limit:.0%}——超过即失败。
5. 不输出任何说明、分析、注释——只输出改写后的正文。
6. 不要输出"以下是改写后的正文"等引导语——直接输出正文。

【改写优先级】
1. 先判断能否删除（升华句/总结句/解释腔/全知剧透→直接删）
2. 再考虑润色（禁用词替换、心理外化、句式去套路）
3. 删除后保留原意，不要补写新内容

请改写以下正文：

{text}"""


# ── 系统提示词 ──
DESLOP_SYSTEM_PROMPT = (
    "你是网文去AI味编辑。你的任务是按 oh-story 7 Gate 体系改写文本，"
    "让 AI 检测器认为这是人类写的。铁律：不改编情、不增删角色、"
    "删除比例不超上限、只输出改写后的正文。"
)


# ════════════════════════════════════════════════════════════════════
# 第三部分：后处理器主入口
# ════════════════════════════════════════════════════════════════════


def _format_metrics_summary(score: dict) -> str:
    """格式化 6 项指标为可读字符串。"""
    lines = []
    for m in score["metrics"]:
        lines.append(f"- {m['metric']}: {m['value']}（{m['band']}）")
    lines.append(f"- 中度指标数: {score['moderate_count']}")
    lines.append(f"- 重度指标数: {score['severe_count']}")
    return "\n".join(lines)


def _select_passes(level: str) -> list[tuple[str, str]]:
    """按 AI 味等级选择 Pass 序列。

    返回 [(pass_name, gates_rules), ...]
    - 轻度：Pass1（去泛化）
    - 中度：Pass1 + Pass2（去书面化）
    - 重度：Pass1 + Pass2 + Pass3（回自然感）
    """
    if level == LEVEL_MILD:
        return [("Pass1 去泛化", PASS1_GATES)]
    elif level == LEVEL_MODERATE:
        return [
            ("Pass1 去泛化", PASS1_GATES),
            ("Pass2 去书面化", PASS2_GATES),
        ]
    else:  # LEVEL_SEVERE
        return [
            ("Pass1 去泛化", PASS1_GATES),
            ("Pass2 去书面化", PASS2_GATES),
            ("Pass3 回自然感", PASS3_GATES),
        ]


async def run_deslop_postprocess(
    text: str,
    llm_client: Any,
    *,
    force_run: bool = False,
    max_passes: int | None = None,
) -> dict:
    """运行完整 7 Gate 去 AI 味后处理。

    流程：
    1. 确定性检测：无 blocking 且 advisory≤2 且 force_run=False 时直接返回（节省 token）
    2. 计算 6 项客观指标，确定 AI 味等级
    3. 按等级选择 Pass 序列（轻度=1遍/中度=2遍/重度=3遍）
    4. 顺序执行每遍 LLM 改写
    5. 二次验证：改写后仍不通过则回退原版本

    参数：
    - text: 待处理正文
    - llm_client: LLMClient 实例（需有 async generate 方法）
    - force_run: True 时即使确定性检测通过也强制跑 LLM
    - max_passes: 限制最大 Pass 数（用于测试/调试）

    返回：{
        "original_text": str,
        "processed_text": str,
        "level": "mild"/"moderate"/"severe",
        "score": {...},  # 6 项指标
        "passes_executed": [pass_name, ...],
        "skipped": bool,  # 是否跳过 LLM 调用
        "rolled_back": bool,  # 是否回退原版本
        "pre_check": {...},  # 处理前确定性检测结果
        "post_check": {...},  # 处理后确定性检测结果
    }
    """
    original = text
    result = {
        "original_text": original,
        "processed_text": original,
        "level": LEVEL_MILD,
        "score": None,
        "passes_executed": [],
        "skipped": False,
        "rolled_back": False,
        "pre_check": None,
        "post_check": None,
    }

    # ── Step 1: 确定性检测 ──
    pre_check = run_deslop_checks(text)
    result["pre_check"] = {
        "blocking_count": pre_check["blocking_count"],
        "advisory_count": pre_check["advisory_count"],
        "soft_count": pre_check["soft_count"],
        "passed": pre_check["passed"],
    }

    # 跳过条件：无 blocking 且 advisory ≤ 2 且未强制运行
    if not force_run and pre_check["passed"] and pre_check["advisory_count"] <= 2:
        logger.info("deslop_postprocess: 确定性检测通过（blocking=0, advisory=%d），跳过 LLM 调用",
                   pre_check["advisory_count"])
        result["skipped"] = True
        result["post_check"] = result["pre_check"]
        return result

    # ── Step 2: 计算 6 项客观指标 ──
    score = score_ai_level(text)
    result["level"] = score["level"]
    result["score"] = score
    logger.info("deslop_postprocess: AI 味等级=%s, moderate=%d, severe=%d",
               score["level"], score["moderate_count"], score["severe_count"])

    # ── Step 3: 选择 Pass 序列 ──
    passes = _select_passes(score["level"])
    if max_passes is not None:
        passes = passes[:max_passes]

    delete_limit = DELETE_RATIO_LIMIT[score["level"]]
    metrics_summary = _format_metrics_summary(score)

    # ── Step 4: 顺序执行 Pass ──
    current_text = text
    for pass_name, gates_rules in passes:
        prompt = _build_pass_prompt(
            pass_name=pass_name,
            gates_rules=gates_rules,
            text=current_text,
            delete_ratio_limit=delete_limit,
            ai_level=score["level"],
            metrics_summary=metrics_summary,
        )
        try:
            rewritten = await llm_client.generate(
                prompt, system=DESLOP_SYSTEM_PROMPT,
            )
            if rewritten and len(rewritten.strip()) > 0:
                # 删除比例校验：不应大幅缩短
                orig_cn = _count_chinese(current_text)
                new_cn = _count_chinese(rewritten)
                if orig_cn > 0:
                    shrink_ratio = 1 - new_cn / orig_cn
                    if shrink_ratio > delete_limit + 0.10:  # 容忍 10% 误差
                        logger.warning(
                            "deslop_postprocess %s: 删除比例 %.0f%% 超过上限 %.0f%%，跳过本遍",
                            pass_name, shrink_ratio * 100, delete_limit * 100,
                        )
                        # 仍记录已执行，但保留原文
                    else:
                        current_text = rewritten.strip()
                else:
                    current_text = rewritten.strip()
                result["passes_executed"].append(pass_name)
                logger.info("deslop_postprocess: %s 完成", pass_name)
        except Exception as e:
            logger.warning("deslop_postprocess %s 失败: %s", pass_name, e)
            # 单遍失败不阻塞，继续下一遍

    result["processed_text"] = current_text

    # ── Step 4.5: 确定性标点兜底（机械清理 ……/——/—/-- 残留） ──
    # 对齐 oh-story SKILL.md Phase 3.5（行 323-339）：LLM 改写后机械兜底
    # 保证 em-dash blocking 检测在 post_check 中通过
    try:
        before_norm = current_text
        current_text = normalize_punctuation(current_text)
        if current_text != before_norm:
            result["processed_text"] = current_text
            logger.info("deslop_postprocess: 标点兜底清理完成")
    except Exception as e:
        logger.warning("deslop_postprocess: 标点兜底失败（忽略）: %s", e)

    # ── Step 5: 二次验证 ──
    post_check = run_deslop_checks(current_text)
    result["post_check"] = {
        "blocking_count": post_check["blocking_count"],
        "advisory_count": post_check["advisory_count"],
        "soft_count": post_check["soft_count"],
        "passed": post_check["passed"],
    }

    # 如果改写后 blocking 反而增多，回退原版本
    if post_check["blocking_count"] > pre_check["blocking_count"]:
        logger.warning(
            "deslop_postprocess: 改写后 blocking 增多（%d→%d），回退原版本",
            pre_check["blocking_count"], post_check["blocking_count"],
        )
        result["processed_text"] = original
        result["rolled_back"] = True
        # 重新计算 post_check
        result["post_check"] = result["pre_check"]

    return result


# ════════════════════════════════════════════════════════════════════
# 第四部分：便捷工具函数
# ════════════════════════════════════════════════════════════════════


# ── 确定性标点兜底（移植 oh-story normalize-punctuation.js） ──
# 对齐 oh-story scripts/normalize-punctuation.js:1-277
# LLM 改写后机械清理残留 ……/——/—/--/---，保证标点残留为 0

# 因果连词前的省略号/破折号改冒号（对齐 oh-story choosePauseReplacement:202-219）
_CAUSAL_PREFIXES = (
    "因为", "原来", "这是", "那是", "也就是", "换句话", "说白了",
    "所谓", "答案", "原因", "结果", "真相", "问题在于",
)

# 句末标点集（省略号/破折号在句末标点前应删除）
_SENTENCE_END_PUNCT = set("。！？!?；;")

# 引号闭字符（省略号/破折号在闭引号前改句号）
# 用 Unicode 码点明确指定，避免字符串解析歧义
_CLOSE_QUOTE_CHARS = {
    '\u300D',  # 」 日中右单角引号
    '\u300F',  # 』 日中右双角引号
    '\u201D',  # " 中文右双引号
    '\u2019',  # ' 中文右单引号
    '"',       # ASCII 双引号（开闭同）
    "'",       # ASCII 单引号（开闭同）
    '）',       # 中文右括号
    '】',       # 中文右方括号
}


def normalize_punctuation(text: str) -> str:
    """确定性标点兜底：机械清理残留的 ……/——/—/--/---。

    移植 oh-story normalize-punctuation.js 的核心规则：
    1. 独立行 ---（markdown 分隔线）→ 删除整行
    2. ……/——/—/-- 智能替换：
       - 数字间 → "到"（如"5——10" → "5到10"）
       - 闭引号前 → "。"（对话被截断收尾）
       - 因果连词前 → "："（引出解释）
       - 句末标点前 → 删除（"……。" → "。"）
       - 标点后 → 删除（"。……" → "。"）
       - 其他 → "，"（默认节奏停顿）

    保证 LLM 改写后 ……/—— 残留为 0，是 deslop 的最后一道机械防线。
    """
    if not text:
        return text

    # 1. 删除独立行 ---（markdown 分隔线）
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if line.strip() == "---" or line.strip() == "***" or line.strip() == "___":
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 2. 智能替换 ……/——/—/--/---
    # 先处理 ---（3+ 连字符），再 ——，再 单 —，再 ……，再 --+
    # 用占位符避免重复替换

    # ---（3+ 连字符，markdown 分隔线残留）→ 删除
    text = re.sub(r'-{3,}', '', text)

    # —— （中文双破折号）
    text = _replace_pause(text, r'——')
    # —（单个 em dash，非数字范围）
    text = re.sub(r'(?<![\d—])—(?![\d—])', lambda m: _choose_replacement(text, m.start(), m.end()), text)
    # ……（中文省略号）
    text = _replace_pause(text, r'……')
    # …（单个省略号字符）
    text = re.sub(r'…', lambda m: _choose_replacement(text, m.start(), m.end()), text)
    # --+（ASCII 连字符 2+）
    text = _replace_pause(text, r'-{2,}')

    # 清理可能产生的连续逗号/句号
    text = re.sub(r'，\s*，+', '，', text)
    text = re.sub(r'。\s*。+', '。', text)

    return text


def _replace_pause(text: str, pattern: str) -> str:
    """对指定 pause 模式（如 —— / …… / --+）逐处智能替换。"""
    def _sub(m):
        return _choose_replacement(text, m.start(), m.end())
    return re.sub(pattern, _sub, text)


def _choose_replacement(text: str, start: int, end: int) -> str:
    """根据上下文选择省略号/破折号的替换字符串。

    对齐 oh-story normalize-punctuation.js choosePauseReplacement:159-219。
    """
    # 前后字符（边界外）
    prev_char = text[start - 1] if start > 0 else ""
    next_char = text[end] if end < len(text) else ""

    # 数字间 → "到"（如 5——10）
    if prev_char.isdigit() and next_char.isdigit():
        return "到"

    # 闭引号前 → "。"（对话被截断收尾）
    if next_char in _CLOSE_QUOTE_CHARS:
        return "。"

    # 因果连词前 → "："（引出解释）
    remaining = text[end:end + 6]
    if any(remaining.startswith(p) for p in _CAUSAL_PREFIXES):
        return "："

    # 句末标点前 → 删除（……。 → 。）
    if next_char in _SENTENCE_END_PUNCT:
        return ""

    # 标点后 → 删除（。…… → 。）
    if prev_char in _SENTENCE_END_PUNCT or prev_char in _CLOSE_QUOTE_CHARS:
        return ""

    # 其他 → 逗号（默认节奏停顿）
    return "，"





def should_run_deslop(text: str) -> tuple[bool, str]:
    """快速判断是否需要运行 deslop 后处理。

    返回 (need_run, reason)：
    - 无 blocking 且 advisory≤2 → (False, "确定性检测通过")
    - 有 blocking → (True, "存在 blocking 级 AI 模式")
    - advisory>2 → (True, "advisory 级问题过多")
    """
    check = run_deslop_checks(text)
    if not check["passed"]:
        return True, f"存在 {check['blocking_count']} 个 blocking 级 AI 模式"
    if check["advisory_count"] > 2:
        return True, f"advisory 级问题过多（{check['advisory_count']}）"
    return False, "确定性检测通过"


def get_deslop_summary(result: dict) -> str:
    """格式化 deslop 后处理结果为可读字符串（用于日志/UI）。"""
    if result["skipped"]:
        return f"deslop 跳过（确定性检测通过）"

    parts = [
        f"AI味等级: {result['level']}",
        f"执行 Pass: {', '.join(result['passes_executed']) or '无'}",
    ]
    if result["rolled_back"]:
        parts.append("已回退原版本（改写后问题增多）")
    pre = result.get("pre_check") or {}
    post = result.get("post_check") or {}
    parts.append(
        f"blocking: {pre.get('blocking_count', 0)}→{post.get('blocking_count', 0)}, "
        f"advisory: {pre.get('advisory_count', 0)}→{post.get('advisory_count', 0)}"
    )
    return " | ".join(parts)
