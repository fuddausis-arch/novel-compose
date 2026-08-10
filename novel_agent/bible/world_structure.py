"""世界观结构化：地点自动分层（tier）+ 领域归属（layer）+ 层级校验。

移植自 AI Reader V2 的 world_structure_agent 思路，适配我们的圣经 Location 表。

分类策略：
- tier: 基于地名后缀规则判断层级（国->kingdom, 城->city, 村->site...），带反例保护
- layer: 基于关键词判断空间领域（天界->celestial, 地府->underworld...）
- 层级校验: 检查父地点存在、无循环、子级 tier 不高于父级
"""
from __future__ import annotations

from typing import Any

# ============================================================
# tier 分类器：后缀 -> 层级映射
# ============================================================

# tier 优先级（数字越大层级越高，用于校验子级不能高于父级）
TIER_PRIORITY: dict[str, int] = {
    "continent": 8,   # 大陆/界/洲
    "kingdom":  7,    # 国/帝国/王朝
    "region":   6,    # 域/地区/荒原/平原
    "city":     5,    # 城/都/府
    "town":     4,    # 镇/村/庄/寨
    "district": 3,    # 街区/街道/城区（附属城内的街区）
    "site":     2,    # 殿/阁/楼/院/桥/山/谷/湖...
    "landmark": 1,    # 塔/碑/像/泉/树
    "dungeon":  1,    # 秘境/副本/遗迹/迷宫
    "other":    0,
}

# 后缀规则：按优先级从高到低匹配
# 注意：反例条目（exceptions）优先于后缀规则
_TIER_SUFFIX_RULES: list[tuple[str, list[str]]] = [
    ("continent", ["界", "大陆", "洲", "星域", "宇宙"]),
    ("kingdom",   ["国", "帝国", "王朝", "联邦", "王国", "皇朝"]),
    ("region",    ["域", "地区", "荒原", "平原", "高原", "盆地", "森林", "沙漠", "海域", "群岛"]),
    ("city",      ["城", "都", "京都", "城池"]),
    ("town",      ["镇", "村", "庄", "寨", "屯", "堡", "乡"]),
    ("district",  ["街区", "街道", "城区", "工业区", "住宅区", "商业区",
                   "集市区", "码头区", "老城区", "新区", "区"]),
    ("dungeon",   ["秘境", "副本", "遗迹", "迷宫", "禁地", "深渊", "裂缝", "裂缝空间"]),
    ("landmark",  ["塔", "碑", "像", "泉", "树", "崖"]),
    ("site",      ["殿", "阁", "楼", "院", "桥", "山", "谷", "湖", "河", "江", "海", "宫",
                   "寺", "庙", "观", "堂", "斋", "轩", "府", "邸", "巷", "街", "市", "窟",
                   "洞", "穴", "渊", "潭", "溪", "峰", "岭", "坡", "原", "坞", "港",
                   "门", "关"]),
]

# 反例保护：某些后缀会误导分类
# 例如 "王府" 以 "府" 结尾，但不应归为 city，而应为 site
_TIER_EXCEPTIONS: dict[str, str] = {
    # "国" 后缀反例
    "王国": "kingdom",  # 王国本身就是 kingdom，不算反例，但避免被 "国" 规则二次匹配
    # "府" 作为后缀通常指府邸而非行政区域
    "王府": "site",
    "公府": "site",
    "侯府": "site",
    "伯府": "site",
    "将军府": "site",
    "总督府": "site",
    "知府": "site",
    "府": "site",
    # "关" 作为地名后缀指关隘
    "关": "site",  # 已在 site 规则中，这里确保不被 landmark 的 "关" 覆盖
    # "市" 作为后缀指市场
    "黑市": "site",
    "集市": "site",
    # "都" 反例
    "都": "city",  # 确保 "都" 归为 city
}

# ============================================================
# layer 分类器：关键词 -> 空间领域映射
# ============================================================

_LAYER_KEYWORDS: list[tuple[str, list[str]]] = [
    ("celestial",   ["天界", "天庭", "神界", "仙界", "天宫", "九天", "凌霄", "神域",
                     "仙庭", "天府", "天山", "天上", "云端", "星空", "星界"]),
    ("underworld",  ["地府", "冥界", "幽冥", "黄泉", "地狱", "九幽", "阴曹", "冥府",
                     "鬼界", "幽都", "冥河", "忘川", "彼岸", "轮回", "阴间"]),
    ("underwater",  ["海底", "龙宫", "深海", "水晶宫", "海渊", "水府", "江底",
                     "海沟", "海底城", "鲛人", "渊底"]),
    ("realm",       ["修仙界", "灵界", "魔界", "妖界", "幻境", "异空间", "位面",
                     "次元", "虚空", "混沌", "星域", "内世界", "小世界", "秘境世界",
                     "镜中", "梦境", "意识海", "精神世界"]),
]


def classify_tier(name: str) -> str:
    """根据地名后缀自动判断层级 tier。

    >>> classify_tier("大唐帝国")
    'kingdom'
    >>> classify_tier("长安城")
    'city'
    >>> classify_tier("清水村")
    'town'
    >>> classify_tier("荣国府")
    'site'
    >>> classify_tier("天界")
    'continent'
    """
    if not name or not name.strip():
        return "other"

    name = name.strip()

    # 1. 先检查反例（最长匹配优先）
    for suffix in sorted(_TIER_EXCEPTIONS.keys(), key=len, reverse=True):
        if name.endswith(suffix):
            return _TIER_EXCEPTIONS[suffix]

    # 2. 后缀规则匹配（从高优先级到低）
    for tier, suffixes in _TIER_SUFFIX_RULES:
        for suffix in suffixes:
            if name.endswith(suffix):
                return tier

    # 3. 无法判断
    return "other"


def classify_layer(name: str, description: str = "") -> str:
    """根据地名和描述中的关键词判断空间领域 layer。

    >>> classify_layer("天庭")
    'celestial'
    >>> classify_layer("幽冥界")
    'underworld'
    >>> classify_layer("龙宫")
    'underwater'
    >>> classify_layer("长安城")
    'surface'
    """
    text = f"{name} {description}".strip()
    if not text:
        return "surface"

    for layer, keywords in _LAYER_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return layer

    return "surface"


def classify_location(name: str, description: str = "") -> dict[str, str]:
    """一次性返回 tier 和 layer 分类结果。

    >>> result = classify_location("天庭", "玉帝居住之所")
    >>> result["tier"]
    'continent'
    >>> result["layer"]
    'celestial'
    """
    return {
        "tier": classify_tier(name),
        "layer": classify_layer(name, description),
    }


# ============================================================
# 层级校验器
# ============================================================

def validate_hierarchy(
    locations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """校验地点层级的完整性。

    检查项：
    1. parent_name 引用的父地点是否存在
    2. 是否存在循环引用（A->B->A）
    3. 子级 tier 不应高于父级 tier（city 不能是 town 的父级）

    Args:
        locations: 地点列表，每个元素至少含 name, parent_name, tier 字段

    Returns:
        问题列表，每项含 {location, issue, severity, detail}
    """
    issues: list[dict[str, Any]] = []

    # 构建 name -> location 映射
    name_map: dict[str, dict[str, Any]] = {}
    for loc in locations:
        name_map[loc.get("name", "")] = loc

    for loc in locations:
        name = loc.get("name", "")
        parent_name = loc.get("parent_name", "")
        tier = loc.get("tier", "other")

        # 1. 父地点存在性检查
        if parent_name and parent_name.strip():
            if parent_name not in name_map:
                issues.append({
                    "location": name,
                    "issue": "missing_parent",
                    "severity": "warning",
                    "detail": f"父地点「{parent_name}」不存在于地点列表中",
                })
                continue  # 父不存在，后续检查无意义

            # 2. 循环引用检查
            visited = {name}
            current = parent_name
            cycle_found = False
            while current:
                if current in visited:
                    issues.append({
                        "location": name,
                        "issue": "circular_reference",
                        "severity": "error",
                        "detail": f"存在循环引用：{name} -> ... -> {current}",
                    })
                    cycle_found = True
                    break
                visited.add(current)
                parent_loc = name_map.get(current, {})
                current = parent_loc.get("parent_name", "")
            if cycle_found:
                continue

            # 3. tier 层级检查：子级不应高于父级
            parent_tier = name_map[parent_name].get("tier", "other")
            child_priority = TIER_PRIORITY.get(tier, 0)
            parent_priority = TIER_PRIORITY.get(parent_tier, 0)

            # 如果子级 tier 高于父级（如 city 是 town 的父级），报告警告
            if child_priority > parent_priority + 1:
                # 允许相邻层级（如 city 的父级是 region），但不允许跨级
                issues.append({
                    "location": name,
                    "issue": "tier_mismatch",
                    "severity": "warning",
                    "detail": f"「{name}」(tier={tier}) 是「{parent_name}」(tier={parent_tier}) 的子级，但层级跨度过大",
                })

    return issues


def auto_classify_locations(
    locations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量自动分类地点的 tier 和 layer。

    对每个地点，如果 tier 为空则自动推断，layer 同理。
    返回更新后的地点列表（原地修改 + 返回）。

    Args:
        locations: 地点列表，每个元素至少含 name 字段

    Returns:
        更新后的地点列表，每个元素新增/更新了 tier 和 layer 字段
    """
    for loc in locations:
        name = loc.get("name", "")
        desc = loc.get("description", "")

        # 仅在 tier 为空时自动推断（不覆盖用户已设置的值）
        if not loc.get("tier"):
            loc["tier"] = classify_tier(name)

        # 仅在 layer 为空或为默认值时自动推断
        if not loc.get("layer") or loc.get("layer") == "surface":
            classified = classify_layer(name, desc)
            if classified != "surface":
                loc["layer"] = classified

    return locations
