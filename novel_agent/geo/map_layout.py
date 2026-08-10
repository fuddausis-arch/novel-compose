"""地图布局引擎（纯 Python，无 scipy 依赖）。

混合方案（可视化融合 P3）：
1. LLM 只输出**语义约束**（方位 direction + 相对参照 relative_to + layer 归属），
   不输出精确坐标——一次调用、token 极省、失败可回退。
2. 引擎把语义约束转成**弹簧力学模型**迭代求解精确坐标：
   - 同 layer（领域）的地点聚集在同一区域带（天界在上、幽冥在下、海底更下）
   - 父子（contains）关系地点强吸引
   - adjacent/road 关系地点按距离约束
   - portal 关系可远
   - 方位语义作为初始锚点偏置（北→上方、南→下方、东→右、西→左、中心→中间）
   - 所有地点互斥防重叠（力导向斥力）

附带收益：合并了 importance 同心圆等手写布局，统一走约束求解。
"""
from __future__ import annotations

import math
import random
from typing import Any

# ---- 语义方位常量 ----

DIRECTION_HINTS = {
    "north": (0.0, -1.0), "n": (0.0, -1.0), "北": (0.0, -1.0), "北方": (0.0, -1.0),
    "south": (0.0, 1.0), "s": (0.0, 1.0), "南": (0.0, 1.0), "南方": (0.0, 1.0),
    "east": (1.0, 0.0), "e": (1.0, 0.0), "东": (1.0, 0.0), "东方": (1.0, 0.0),
    "west": (-1.0, 0.0), "w": (-1.0, 0.0), "西": (-1.0, 0.0), "西方": (-1.0, 0.0),
    "center": (0.0, 0.0), "c": (0.0, 0.0), "中心": (0.0, 0.0), "中央": (0.0, 0.0),
    "northeast": (0.707, -0.707), "ne": (0.707, -0.707), "东北": (0.707, -0.707),
    "northwest": (-0.707, -0.707), "nw": (-0.707, -0.707), "西北": (-0.707, -0.707),
    "southeast": (0.707, 0.707), "se": (0.707, 0.707), "东南": (0.707, 0.707),
    "southwest": (-0.707, 0.707), "sw": (-0.707, 0.707), "西南": (-0.707, 0.707),
}

# layer → 垂直带（y 方向归一化偏移：-1 最上，+1 最下）
LAYER_BAND = {
    "celestial": -1.0,     # 天界：最上
    "realm": -0.4,         # 独立界域：偏上
    "surface": 0.0,        # 地表：中间
    "underworld": 0.7,     # 幽冥：偏下
    "underwater": 1.0,     # 海底：最下
    "other": 0.0,
    "": 0.0,
}

# 关系类型 → 期望距离（px）
REL_REST_LENGTH = {
    "contains": 180.0,
    "adjacent": 260.0,
    "road": 420.0,
    "portal": 900.0,
    "warzone": 520.0,
}

_LAYER_WEIGHT = 0.0      # layer 带内聚集权重
_DIRECTION_WEIGHT = 0.15  # 方位锚点权重（随迭代衰减）
_PARENT_WEIGHT = 1.4      # 父子吸引权重
_EDGE_WEIGHT = 1.0        # 普通关系吸引权重
_REPULSION = 2600.0       # 全局斥力强度


def _normalize(dx: float, dy: float) -> tuple[float, float]:
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return 0.0, 0.0
    return dx / d, dy / d


def layout_map(locations: list[dict], rels: list[dict], hints: dict | None = None,
               width: float = 1800, height: float = 1300,
               iterations: int = 120) -> dict[int, dict]:
    """把地点列表 + 关系 + 语义提示求解为精确坐标。

    Args:
        locations: [{"id": int, "name": str, "type": str, "layer": str,
                     "parent_name": str, "importance": str}, ...]
        rels: [{"source": str, "target": str, "relation_type": str}, ...]
                 source/target 是地点名
        hints: {location_name: {"direction": "north"|"south"|...,
                                "relative_to": "某地点名"}} 可空
        width/height: 画布范围

    Returns:
        {location_id: {"x": int, "y": int}}
    """
    n = len(locations)
    if n == 0:
        return {}
    hints = hints or {}

    # 构建 id ↔ name 映射
    id_by_name = {loc["name"]: loc["id"] for loc in locations}
    name_by_id = {loc["id"]: loc["name"] for loc in locations}
    layer_by_id = {loc["id"]: (loc.get("layer") or "surface") for loc in locations}
    parent_of_id = {loc["id"]: loc.get("parent_name") or "" for loc in locations}

    # 初始位置：方位锚点 + layer 带 + 随机微扰
    rng = random.Random(42)
    pos: dict[int, list[float]] = {}
    for loc in locations:
        lid = loc["id"]
        hint = hints.get(loc["name"]) or {}
        dx, dy = DIRECTION_HINTS.get(hint.get("direction", ""), (0.0, 0.0))
        rel_to = hint.get("relative_to")
        if rel_to and rel_to in id_by_name:
            # 相对参照：放在参照物方向外侧
            ref_id = id_by_name[rel_to]
            ref_pos = pos.get(ref_id, [width / 2, height / 2])
            x = ref_pos[0] + dx * 320.0
            y = ref_pos[1] + dy * 320.0
        else:
            x = width / 2 + dx * width * 0.32
            y = height / 2 + dy * height * 0.32
        # layer 带：垂直偏置
        y += LAYER_BAND.get(layer_by_id[lid], 0.0) * height * 0.22
        x += rng.uniform(-40, 40)
        y += rng.uniform(-40, 40)
        pos[lid] = [x, y]

    # 边：id → id（去重，保留最大权重关系）
    edges: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for r in rels:
        src = id_by_name.get(r.get("source", ""))
        tgt = id_by_name.get(r.get("target", ""))
        if src is None or tgt is None or src == tgt:
            continue
        key = (min(src, tgt), max(src, tgt))
        if key in seen:
            continue
        seen.add(key)
        edges.append((src, tgt, r.get("relation_type") or "road"))

    # 父子关系边（强吸引）
    parent_edges: list[tuple[int, int]] = []
    for lid, pname in parent_of_id.items():
        pid = id_by_name.get(pname)
        if pid is not None and pid != lid:
            parent_edges.append((lid, pid))

    # 迭代求解：弹簧力学（斥力 + 边吸引 + 父子吸引 + 方位锚点衰减）
    for it in range(iterations):
        alpha = 1.0 - it / iterations  # 温度衰减
        force: dict[int, list[float]] = {lid: [0.0, 0.0] for lid in pos}

        # 1. 斥力（所有点对）
        ids = list(pos.keys())
        for i in range(n):
            for j in range(i + 1, n):
                a, b = ids[i], ids[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d2 = dx * dx + dy * dy
                if d2 < 1e-6:
                    d2 = 1e-6
                d = math.sqrt(d2)
                f = _REPULSION / d2
                ux, uy = dx / d, dy / d
                force[a][0] += ux * f
                force[a][1] += uy * f
                force[b][0] -= ux * f
                force[b][1] -= uy * f

        # 2. 关系边吸引（按类型期望距离）
        for a, b, rtype in edges:
            rest = REL_REST_LENGTH.get(rtype, 420.0)
            _apply_spring(force, pos, a, b, rest, _EDGE_WEIGHT)

        # 3. 父子吸引（更近）
        for a, b in parent_edges:
            _apply_spring(force, pos, a, b, 140.0, _PARENT_WEIGHT)

        # 4. 同 layer 聚类（轻微）
        for i in range(n):
            for j in range(i + 1, n):
                a, b = ids[i], ids[j]
                if layer_by_id.get(a) and layer_by_id.get(a) == layer_by_id.get(b):
                    _apply_spring(force, pos, a, b, 520.0, _LAYER_WEIGHT)

        # 5. 方位锚点（初始阶段强，后期弱）
        for loc in locations:
            lid = loc["id"]
            hint = hints.get(loc["name"]) or {}
            if not hint:
                continue
            dx, dy = DIRECTION_HINTS.get(hint.get("direction", ""), (0.0, 0.0))
            if dx == 0 and dy == 0:
                continue
            target_x = width / 2 + dx * width * 0.32
            target_y = height / 2 + dy * height * 0.32
            # 相对参照则锚到参照物外侧
            rel_to = hint.get("relative_to")
            if rel_to and rel_to in id_by_name:
                ref_id = id_by_name[rel_to]
                ref_pos = pos.get(ref_id, [width / 2, height / 2])
                target_x = ref_pos[0] + dx * 320.0
                target_y = ref_pos[1] + dy * 320.0
            force[lid][0] += (target_x - pos[lid][0]) * _DIRECTION_WEIGHT
            force[lid][1] += (target_y - pos[lid][1]) * _DIRECTION_WEIGHT

        # 6. 施加力 + 阻尼
        for lid in ids:
            pos[lid][0] += force[lid][0] * 0.12 * alpha
            pos[lid][1] += force[lid][1] * 0.12 * alpha
            # 边界约束
            pos[lid][0] = min(max(pos[lid][0], 80.0), width - 80.0)
            pos[lid][1] = min(max(pos[lid][1], 80.0), height - 80.0)

    return {lid: {"x": int(round(p[0])), "y": int(round(p[1]))} for lid, p in pos.items()}


def _apply_spring(force: dict, pos: dict, a: int, b: int, rest: float, weight: float) -> None:
    """弹簧吸引：距离越远拉得越狠。"""
    dx = pos[b][0] - pos[a][0]
    dy = pos[b][1] - pos[a][1]
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return
    disp = d - rest
    f = disp * 0.02 * weight
    ux, uy = dx / d, dy / d
    force[a][0] += ux * f
    force[a][1] += uy * f
    force[b][0] -= ux * f
    force[b][1] -= uy * f


def parse_semantic_hints(raw: str) -> dict:
    """解析 LLM 返回的语义约束 JSON 为 {地点名: {"direction":..., "relative_to":...}}。

    兼容 ```json ... ``` 包裹与首尾花括号包裹。
    无效内容返回空 dict（引擎照常纯算法布局）。
    """
    import json
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.startswith("```"))
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return {}
    try:
        arr = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(arr, list):
        return {}
    hints: dict[str, dict] = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        h: dict[str, Any] = {}
        direction = str(item.get("direction") or "").strip().lower()
        if direction in DIRECTION_HINTS:
            h["direction"] = direction
        rel_to = str(item.get("relative_to") or "").strip()
        if rel_to:
            h["relative_to"] = rel_to
        if h:
            hints[name] = h
    return hints
