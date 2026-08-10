"""编排层常量配置：语料库标签、题材亲和度、温度映射等。

这些配置与具体节点实现解耦，便于独立调整、测试和复用。
"""
from __future__ import annotations

# ── 语料库按书打标签 ── 每本书代表不同的方向特长 ──
BOOK_TAGS: dict[str, list[str]] = {
    "序列：吃神者 - 不要大脑要小脑":           ["cthulhu", "power", "wasteland", "combat", "politics", "dark"],
    "时停时停时停时停时停时停时停！ - 六个葫芦":  ["cthulhu", "power", "wasteland", "combat", "taboo"],
    "异兽迷城 - 彭湃":                         ["mutation", "power", "combat", "humanity", "mystery"],
    "灵异复苏，永夜降临 - 庆元职高小天才":       ["cthulhu", "horror", "mystery", "dark"],
    "我在精神病院学斩神 - 三九音域":            ["combat", "myth", "power", "cthulhu"],
    "我不是戏神 - 三九音域":                    ["apocalypse", "power", "combat", "mystery"],
    "我无限回档，洞悉所有底牌 - 六个葫芦":       ["cthulhu", "horror", "combat", "dark", "mystery"],
    "十日终焉 - 杀虫队队员":                    ["mystery", "horror", "humanity", "dark", "power"],
    "末日降临？我先降临！ - 板面王仔":           ["wasteland", "survival", "combat", "apocalypse", "power"],
}

# beat_type 关键词 → 标签映射
BEAT_TAG_MAP: dict[str, list[str]] = {
    "cthulhu":    ["古神", "邪神", "低语", "呓语", "不可名状", "理智", "san", "污染", "侵蚀",
                  "旧日", "支配", "深渊", "触手", "诅咒", "疯狂", "寄生", "禁忌", "呓语", "凝视"],
    "power":      ["异能", "觉醒", "序列", "能力", "进化", "权柄", "代价", "异化", "畸变",
                  "超凡", "天赋", "神格", "本源", "法则", "吞噬", "变异"],
    "wasteland":  ["废土", "废墟", "辐射", "荒野", "避难所", "安全区", "聚集地", "变异体",
                  "畸变体", "堡垒", "壁垒"],
    "survival":   ["丧尸", "围城", "感染", "尸潮", "物资", "幸存者", "求生", "食物", "短缺"],
    "combat":     ["搏杀", "厮杀", "猎杀", "围剿", "越级", "斩杀", "激战", "死战",
                  "血腥", "杀戮", "反杀", "对决", "交战"],
    "horror":     ["诡异", "规则", "怪谈", "灵异", "恐怖", "压抑", "阴森", "诡异降临"],
    "myth":       ["神明", "神话", "怪物", "古神", "旧日", "支配者", "邪神", "神兽"],
    "apocalypse":  ["灾变", "灾厄", "末日", "文明崩塌", "末世", "灾难", "大灾变"],
    "humanity":   ["信任", "背叛", "救赎", "抉择", "人性", "牺牲", "羁绊", "温暖"],
    "dark":       ["绝望", "黑暗", "压抑", "崩溃", "残忍", "疯狂", "窒息"],
    "politics":   ["势力", "权谋", "阴谋", "博弈", "算计", "背叛", "阵营"],
    "taboo":      ["收容", "禁忌", "禁忌物", "规则", "异常"],
}

# ── 题材→语感库亲和度映射 ──
# 只有题材匹配时才注入对应语感，防止跨题材污染（如都市文被注入末日语感）
GENRE_TAG_AFFINITY: dict[str, list[str]] = {
    "废土": ["wasteland", "apocalypse", "survival", "power", "combat", "dark"],
    "末日": ["wasteland", "apocalypse", "survival", "power", "combat", "dark"],
    "末世": ["wasteland", "apocalypse", "survival", "power", "combat", "dark"],
    "克苏鲁": ["cthulhu", "horror", "mystery", "dark"],
    "异能": ["power", "combat", "mutation", "mystery"],
    "规则怪谈": ["horror", "mystery", "cthulhu", "taboo", "dark"],
    "悬疑": ["horror", "mystery", "dark"],
    "恐怖": ["horror", "mystery", "dark"],
    "诡异": ["cthulhu", "horror", "mystery", "dark"],
    "黑暗": ["dark", "horror", "combat"],
}

# narrative_function → temperature 映射
TEMP_MAP: dict[str, float] = {
    "战斗": 0.6,       # 战斗需要紧凑逻辑，降低随机性
    "智斗": 0.4,       # 推理博弈需要严谨
    "高潮": 0.9,       # 高潮允许更激烈的创意
    "冲突": 0.8,       # 冲突场景需要爆发力
    "转折": 0.7,       # 转折需要出人意料但合逻辑
    "揭示": 0.5,       # 揭示需要精准信息控制
    "开篇钩子": 0.85,  # 开篇要抓眼球
    "人物塑造": 0.9,   # 人物塑造需要细腻情感
    "关系建立": 0.85,  # 关系互动需要温度
    "悬念设置": 0.7,   # 悬念需要克制
    "铺垫": 0.6,       # 铺垫需要稳重
    "过渡": 0.6,       # 过渡不需要太多创意
    "收束": 0.5,       # 收束需要收得住
    "伏笔": 0.6,       # 伏笔需要精确
    "挫折": 0.8,       # 挫折需要情感冲击
    "世界观铺陈": 0.5, # 设定传递需要准确
}
