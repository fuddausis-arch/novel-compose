"""小说内容图谱 API：CRUD + 一键生成（人物/势力/伏笔/章节）。

图谱数据存 graphs 表，graph_data 字段存 ReactFlow 的 {nodes, edges} JSON。
一键生成从圣经数据库拉数据，自动布局后返回图结构。
"""
from __future__ import annotations

import json
import logging
import math
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Graph
from novel_agent.config import load_config

router = APIRouter()
logger = logging.getLogger(__name__)


# ===== 数据库会话 =====
def get_db():
    """全局图谱数据库会话（与项目无关，graphs 表自带 project_id）。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===== Pydantic 输入模型 =====
class GraphInput(BaseModel):
    name: str
    graph_type: str = "custom"  # characters|factions|foreshadows|chapters|map|custom
    description: str = ""
    graph_data: dict = {"nodes": [], "edges": []}
    is_auto: bool = False


class GraphUpdateInput(BaseModel):
    name: str | None = None
    description: str | None = None
    graph_data: dict | None = None


class AutoGenerateInput(BaseModel):
    graph_type: str  # characters|factions|foreshadows|chapters|map
    name: str | None = None


class LocationInput(BaseModel):
    name: str
    type: str = "city"           # city/region/landmark/secret/dungeon/other
    description: str = ""
    parent_name: str = ""
    coord_x: int = 0
    coord_y: int = 0
    importance: str = ""
    tier: str = ""               # kingdom/continent/region/city/town/site/dungeon/landmark/other
    layer: str = "surface"       # surface/celestial/underworld/underwater/realm/other


class LocationRelationshipInput(BaseModel):
    source_location: str
    target_location: str
    relation_type: str = "road"  # road/adjacent/contains/portal/warzone
    distance: str = ""
    description: str = ""


# ===== 序列化 =====
def _graph_dict(g: Graph) -> dict:
    return {
        "id": g.id,
        "project_id": g.project_id,
        "name": g.name,
        "graph_type": g.graph_type,
        "description": g.description,
        "graph_data": g.graph_data or {"nodes": [], "edges": []},
        "is_auto": g.is_auto,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


# ===== CRUD =====
@router.get("/{project_id}/graphs")
def list_graphs(project_id: int, db: Session = Depends(get_db)):
    """列出项目的所有图谱。"""
    items = db.query(Graph).filter(Graph.project_id == project_id).order_by(Graph.updated_at.desc()).all()
    return [_graph_dict(g) for g in items]


@router.get("/{project_id}/graphs/{graph_id}")
def get_graph(project_id: int, graph_id: int, db: Session = Depends(get_db)):
    g = db.query(Graph).filter(Graph.project_id == project_id, Graph.id == graph_id).first()
    if not g:
        raise HTTPException(404, "图谱不存在")
    return _graph_dict(g)


@router.post("/{project_id}/graphs")
def create_graph(project_id: int, data: GraphInput, db: Session = Depends(get_db)):
    if not data.name.strip():
        raise HTTPException(400, "图谱名称不能为空")
    existing = db.query(Graph).filter(Graph.project_id == project_id, Graph.name == data.name.strip()).first()
    if existing:
        raise HTTPException(409, "图谱名称已存在")
    g = Graph(
        project_id=project_id,
        name=data.name.strip(),
        graph_type=data.graph_type,
        description=data.description,
        graph_data=data.graph_data,
        is_auto=data.is_auto,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _graph_dict(g)


@router.put("/{project_id}/graphs/{graph_id}")
def update_graph(project_id: int, graph_id: int, data: GraphUpdateInput, db: Session = Depends(get_db)):
    g = db.query(Graph).filter(Graph.project_id == project_id, Graph.id == graph_id).first()
    if not g:
        raise HTTPException(404, "图谱不存在")
    if data.name is not None:
        g.name = data.name.strip()
    if data.description is not None:
        g.description = data.description
    if data.graph_data is not None:
        g.graph_data = data.graph_data
    db.commit()
    db.refresh(g)
    return _graph_dict(g)


@router.delete("/{project_id}/graphs/{graph_id}")
def delete_graph(project_id: int, graph_id: int, db: Session = Depends(get_db)):
    g = db.query(Graph).filter(Graph.project_id == project_id, Graph.id == graph_id).first()
    if not g:
        raise HTTPException(404, "图谱不存在")
    db.delete(g)
    db.commit()
    return {"deleted": True}


# ===== 一键生成 =====
@router.post("/{project_id}/graphs/auto-generate")
def auto_generate_graph(project_id: int, data: AutoGenerateInput, db: Session = Depends(get_db)):
    """一键生成图谱：从圣经数据库拉数据，自动布局后返回图结构（不落库）。

    前端拿到结果后可选择「保存」落库。
    """
    graph_type = data.graph_type
    name = data.name or _default_name(graph_type)

    if graph_type == "characters":
        graph_data = _build_characters_graph(project_id, db)
    elif graph_type == "factions":
        graph_data = _build_factions_graph(project_id, db)
    elif graph_type == "foreshadows":
        graph_data = _build_foreshadows_graph(project_id, db)
    elif graph_type == "chapters":
        graph_data = _build_chapters_graph(project_id, db)
    elif graph_type == "map":
        graph_data = _build_map_graph(project_id, db)
    else:
        raise HTTPException(400, f"不支持的图谱类型：{graph_type}")

    return {
        "name": name,
        "graph_type": graph_type,
        "description": _auto_description(graph_type),
        "graph_data": graph_data,
        "is_auto": True,
    }


# ===== 图谱构建逻辑 =====
def _default_name(graph_type: str) -> str:
    names = {
        "characters": "人物关系图",
        "factions": "势力关系图",
        "foreshadows": "伏笔网络图",
        "chapters": "章节脉络图",
        "map": "世界地图",
    }
    return names.get(graph_type, "未命名图谱")


def _auto_description(graph_type: str) -> str:
    descs = {
        "characters": "从圣经数据库自动生成的人物关系图谱",
        "factions": "从圣经数据库自动生成的势力关系图谱",
        "foreshadows": "从圣经数据库自动生成的伏笔网络图谱",
        "chapters": "从圣经数据库自动生成的章节脉络图谱",
        "map": "从圣经数据库自动生成的世界地图",
    }
    return descs.get(graph_type, "")


def _circular_layout(count: int, radius: float = 200, cx: float = 300, cy: float = 250) -> list[dict]:
    """圆形布局：返回 [{x, y}, ...]。

    节点数较多时自动放大半径，避免圆周过密导致节点重叠。
    每个节点至少预留 260px 圆周长（节点宽 240 + 间距 20）。
    """
    positions = []
    if count == 0:
        return positions
    if count == 1:
        return [{"x": cx, "y": cy}]
    # 自适应半径：保证每节点圆周长度 ≥ 260px
    min_circumference = count * 260
    min_radius = min_circumference / (2 * math.pi)
    radius = max(radius, min_radius)
    for i in range(count):
        angle = 2 * math.pi * i / count - math.pi / 2
        positions.append({"x": cx + radius * math.cos(angle), "y": cy + radius * math.sin(angle)})
    return positions


def _grid_layout(count: int, cols: int = 4, dx: float = 260, dy: float = 160, ox: float = 80, oy: float = 80) -> list[dict]:
    """网格布局。

    自适应列数：节点少时减少列数，避免分布稀疏；间距加大避免重叠。
    """
    positions = []
    if count == 0:
        return positions
    # 自适应列数
    if count <= 2:
        cols = count
    elif count <= 4:
        cols = min(cols, 2)
    elif count <= 9:
        cols = 3
    else:
        cols = 4
    for i in range(count):
        row = i // cols
        col = i % cols
        positions.append({"x": ox + col * dx, "y": oy + row * dy})
    return positions


def _layered_circular_layout(items: list, layer_key_fn, max_layers: int = 6,
                              base_radius: float = 160, layer_gap: float = 220,
                              node_arc: float = 280, cx: float = 600, cy: float = 500) -> list[dict]:
    """同心圆分层布局：按重要度分圈，主角/顶层在中心，外圈逐层递减。

    Args:
        items: 待布局对象列表
        layer_key_fn: (item) -> 层级数字(0=最核心/中心, 越大越外圈)
        max_layers: 最大层数
        base_radius: 第 0 层半径(主角/核心节点数=1时用)
        layer_gap: 每层间距
        node_arc: 每节点所需圆周弧长(防重叠)
        cx, cy: 中心坐标

    Returns:
        [{x, y}, ...] 与 items 同序
    """
    if not items:
        return []
    # 按层级分组
    layers: dict[int, list] = {}
    for i, it in enumerate(items):
        layer = layer_key_fn(it)
        if layer < 0 or layer >= max_layers:
            layer = max_layers - 1  # 兜底放最外圈
        layers.setdefault(layer, []).append(i)

    positions = [None] * len(items)
    for layer, indices in sorted(layers.items()):
        count = len(indices)
        if layer == 0 and count <= 1:
            # 核心(主角/顶级势力)单独放正中心
            positions[indices[0]] = {"x": cx, "y": cy}
            continue
        # 外圈半径 = base + layer * gap，且保证圆周够长不重叠
        radius = base_radius + layer * layer_gap
        # 自适应：保证每节点至少 node_arc 弧长
        min_circumference = count * node_arc
        min_radius = min_circumference / (2 * math.pi)
        radius = max(radius, min_radius)
        for j, idx in enumerate(indices):
            angle = 2 * math.pi * j / count - math.pi / 2  # 从顶部开始顺时针
            positions[idx] = {
                "x": cx + radius * math.cos(angle),
                "y": cy + radius * math.sin(angle),
            }
    # 兜底：仍未定位的放外圈
    for i, p in enumerate(positions):
        if p is None:
            positions[i] = {"x": cx + base_radius + max_layers * layer_gap, "y": cy}
    return positions


def _build_characters_graph(project_id: int, db: Session) -> dict:
    """人物关系图：角色为节点，关系为边。

    布局：同心圆分层——主角放正中心，重要人物第1圈，配角第2圈，
    功能性角色第3圈，小人物第4圈，一次性人物/NPC第5圈外圈。
    每个角色按 importance 字段映射到对应层级。
    """
    from novel_agent.bible.models import Character, CharacterRelationship
    from novel_agent.audit.hallucination_filter import filter_appeared

    characters = db.query(Character).filter(Character.project_id == project_id).all()
    rels = db.query(CharacterRelationship).filter(CharacterRelationship.project_id == project_id).all()

    if not characters:
        return {"nodes": [], "edges": []}

    # 幻觉过滤：正文从未出场的角色不进自动图谱（新项目无出场记录时不过滤）
    all_count = len(characters)
    characters = filter_appeared(db, project_id, "character", characters, id_fn=lambda e: e.name)
    if len(characters) < all_count:
        logger.info("人物图幻觉过滤：隐藏 %d 个未出场角色", all_count - len(characters))
    if not characters:
        return {"nodes": [], "edges": []}

    # 角色名 → id 映射
    name_to_id = {c.name: f"char_{c.id}" for c in characters}
    # importance → 层级(0=中心主角, 越大越外圈)
    importance_layer = {
        "主角": 0,
        "核心": 1, "关键人物": 1,
        "配角": 2, "重要": 2,
        "功能性角色": 3, "功能": 3,
        "小人物": 4, "次要": 4,
        "NPC": 5, "背景": 5, "一次性": 5, "边缘": 5,
    }
    importance_color = {
        "主角": "#22c55e",
        "核心": "#f59e0b", "关键人物": "#f59e0b",
        "配角": "#06b6d4", "重要": "#06b6d4",
        "功能性角色": "#8b5cf6", "功能": "#8b5cf6",
        "小人物": "#94a3b8", "次要": "#94a3b8",
        "NPC": "#64748b", "背景": "#64748b", "一次性": "#64748b", "边缘": "#64748b",
    }

    def layer_fn(c):
        imp = (c.importance or "").strip()
        return importance_layer.get(imp, 4)  # 未设定默认放第4圈(小人物层)

    positions = _layered_circular_layout(characters, layer_fn, max_layers=6, cx=600, cy=500)

    nodes = []
    for i, c in enumerate(characters):
        imp = (c.importance or "").strip()
        color = importance_color.get(imp, "#06b6d4")
        # characters 表无 description 字段，用 personality + motivation 拼接
        parts = []
        for field in ["personality", "motivation", "background", "core_contradiction"]:
            v = getattr(c, field, "") or ""
            if v:
                parts.append(v)
        desc = " | ".join(parts)
        nodes.append({
            "id": name_to_id[c.name],
            "type": "dfCharacter",
            "position": positions[i],
            "data": {
                "label": c.name,
                "role": c.role or "",
                "importance": imp or "未设定",
                "color": color,
                "description": desc[:200],
            },
        })

    edges = []
    for r in rels:
        src = name_to_id.get(r.source_character)
        tgt = name_to_id.get(r.target_character)
        if not src or not tgt:
            continue
        # 关系类型 → 颜色
        rel_color = {
            "盟友": "#22c55e",
            "敌人": "#ef4444",
            "师徒": "#8b5cf6",
            "恋人": "#ec4899",
            "亲属": "#f59e0b",
            "主从": "#06b6d4",
        }.get(r.relation_type or "", "#64748b")

        edges.append({
            "id": f"edge_{r.id}",
            "source": src,
            "target": tgt,
            "label": r.relation_type or "",
            "type": "smoothstep",
            "animated": r.is_bidirectional if r.is_bidirectional is not None else False,
            "style": {"stroke": rel_color, "strokeWidth": 2},
            "markerEnd": {"type": "arrowclosed", "color": rel_color},
        })

    return {"nodes": nodes, "edges": edges}


def _build_factions_graph(project_id: int, db: Session) -> dict:
    """势力关系图：势力为节点，势力关系为边。

    布局：同心圆分层——顶级势力放中心，一流第1圈，二流第2圈，
    三流第3圈，隐世势力第4圈外圈。按 tier 字段映射层级。
    注意：FactionRelationship 的 source_faction_id/target_faction_id 存的是势力 id。
    """
    from novel_agent.bible.models import Faction, FactionRelationship
    from novel_agent.audit.hallucination_filter import filter_appeared

    factions = db.query(Faction).filter(Faction.project_id == project_id).all()
    rels = db.query(FactionRelationship).filter(FactionRelationship.project_id == project_id).all()

    if not factions:
        return {"nodes": [], "edges": []}

    # 幻觉过滤：正文从未出场的势力不进自动图谱（新项目无出场记录时不过滤）
    all_count = len(factions)
    factions = filter_appeared(db, project_id, "faction", factions, id_fn=lambda f: str(f.id))
    if len(factions) < all_count:
        logger.info("势力图幻觉过滤：隐藏 %d 个未出场势力", all_count - len(factions))
    if not factions:
        return {"nodes": [], "edges": []}

    # id -> 节点id 映射（关系表存的是势力 id，不是名字）
    id_to_node = {f.id: f"fac_{f.id}" for f in factions}

    # tier → 层级(0=中心顶级, 越大越外圈)
    tier_layer = {
        "顶级势力": 0, "顶级": 0,
        "一流势力": 1, "一流": 1,
        "二流势力": 2, "二流": 2,
        "三流势力": 3, "三流": 3,
        "隐世势力": 4, "隐世": 4,
    }
    tier_color = {
        "顶级势力": "#ef4444", "顶级": "#ef4444",
        "一流势力": "#f59e0b", "一流": "#f59e0b",
        "二流势力": "#06b6d4", "二流": "#06b6d4",
        "三流势力": "#8b5cf6", "三流": "#8b5cf6",
        "隐世势力": "#64748b", "隐世": "#64748b",
    }

    def layer_fn(f):
        tier = (getattr(f, "tier", "") or "").strip()
        return tier_layer.get(tier, 3)  # 未设定默认放第3圈(三流层)

    positions = _layered_circular_layout(factions, layer_fn, max_layers=5, cx=600, cy=500)

    nodes = []
    for i, f in enumerate(factions):
        tier = (getattr(f, "tier", "") or "").strip()
        color = tier_color.get(tier, "#06b6d4")
        desc = getattr(f, "description", "") or getattr(f, "summary", "") or ""
        nodes.append({
            "id": id_to_node[f.id],
            "type": "dfFaction",
            "position": positions[i],
            "data": {
                "label": f.name,
                "type": getattr(f, "type", "") or "",
                "power_level": tier or "未设定",  # 前端字段名保留兼容，显示 tier
                "description": desc[:200],
            },
        })

    edges = []
    for r in rels:
        # FactionRelationship 字段是 source_faction_id / target_faction_id（存势力 id）
        src_id = getattr(r, "source_faction_id", None)
        tgt_id = getattr(r, "target_faction_id", None)
        src = id_to_node.get(src_id) if src_id is not None else None
        tgt = id_to_node.get(tgt_id) if tgt_id is not None else None
        if not src or not tgt:
            continue
        rel_type = getattr(r, "relation_type", "") or ""
        rel_color = {
            "联盟": "#22c55e",
            "敌对": "#ef4444",
            "附属": "#f59e0b",
            "贸易": "#06b6d4",
            "战争": "#dc2626",
        }.get(rel_type, "#64748b")

        edges.append({
            "id": f"edge_{r.id}",
            "source": src,
            "target": tgt,
            "label": rel_type,
            "type": "smoothstep",
            "style": {"stroke": rel_color, "strokeWidth": 2},
            "markerEnd": {"type": "arrowclosed", "color": rel_color},
        })

    return {"nodes": nodes, "edges": edges}


def _build_foreshadows_graph(project_id: int, db: Session) -> dict:
    """伏笔网络图：伏笔为节点，按状态分三栏布局。

    布局：横向三栏——左栏「待回收」(planted)、中栏「已回收」(resolved)、
    右栏「废弃」(abandoned)。每栏内纵向排列。
    依赖关系(depends_on)用虚线边连接。
    """
    from novel_agent.bible.models import Foreshadow

    items = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).all()

    if not items:
        return {"nodes": [], "edges": []}

    # 状态 → 栏位(x 坐标)
    status_col = {
        "planted": 0,    # 待回收 - 左栏
        "resolved": 1,    # 已回收 - 中栏
        "abandoned": 2,   # 废弃 - 右栏
    }
    col_x = [100, 700, 1300]  # 三栏 x 坐标
    col_y_start = 80
    row_gap = 140

    # 按状态分组并排序
    by_status: dict[str, list] = {"planted": [], "resolved": [], "abandoned": []}
    for f in items:
        status = getattr(f, "status", "") or "planted"
        if status not in by_status:
            status = "planted"
        by_status[status].append(f)

    positions: dict[int, dict] = {}
    for status, group in by_status.items():
        col = status_col.get(status, 0)
        for i, f in enumerate(group):
            positions[f.id] = {"x": col_x[col], "y": col_y_start + i * row_gap}

    color_map = {
        "planted": "#f59e0b",     # 待回收（琥珀）
        "resolved": "#22c55e",    # 已回收（绿）
        "abandoned": "#64748b",   # 废弃（灰）
    }

    nodes = []
    for f in items:
        status = getattr(f, "status", "") or "planted"
        if status not in color_map:
            status = "planted"
        color = color_map[status]
        pos = positions.get(f.id, {"x": 0, "y": 0})
        nodes.append({
            "id": f"foreshadow_{f.id}",
            "type": "dfForeshadow",
            "position": pos,
            "data": {
                "label": getattr(f, "foreshadow_id", "") or f"伏笔#{f.id}",
                "description": getattr(f, "description", "") or "",
                "planted_chapter": getattr(f, "plant_chapter", None),
                "resolved_chapter": getattr(f, "resolved_chapter", None),
                "status": status,
                "color": color,
            },
        })

    # 边：依赖关系(depends_on 字段)
    edges = []
    id_map = {f.id: f"foreshadow_{f.id}" for f in items}
    for f in items:
        depends = getattr(f, "depends_on", "") or ""
        if depends:
            for dep_id_str in str(depends).replace("，", ",").split(","):
                dep_id_str = dep_id_str.strip()
                if dep_id_str.isdigit():
                    dep_id = int(dep_id_str)
                    if dep_id in id_map:
                        edges.append({
                            "id": f"edge_dep_{f.id}_{dep_id}",
                            "source": id_map[dep_id],
                            "target": f"foreshadow_{f.id}",
                            "label": "依赖",
                            "type": "smoothstep",
                            "style": {"stroke": "#8b5cf6", "strokeWidth": 2, "strokeDasharray": "5 5"},
                            "markerEnd": {"type": "arrowclosed", "color": "#8b5cf6"},
                        })

    return {"nodes": nodes, "edges": edges}


def _build_chapters_graph(project_id: int, db: Session) -> dict:
    """章节脉络图：按卷→弧→章父子层级构建树状布局。

    策略：分卷纵向布局——卷横向排列，弧在卷下横向排列，章在弧下【纵向】排列。
    这样图呈"窄而高"形态，避免章节多时横向铺得过宽（旧版横向树状 61 章达 13760px，
    fitView 缩到看不清）。章纵向排让用户可上下滚动浏览，符合阅读习惯。
    支持无弧时章直接挂卷下。
    """
    from novel_agent.bible.models import Outline

    outlines = db.query(Outline).filter(Outline.project_id == project_id).order_by(Outline.level, Outline.order).all()

    if not outlines:
        return {"nodes": [], "edges": []}

    # 构建父子映射
    id_to_outline = {o.id: o for o in outlines}
    children_map: dict[int | None, list] = {}
    for o in outlines:
        parent_id = getattr(o, "parent_id", None)
        children_map.setdefault(parent_id, []).append(o)

    level_order = {"volume": 1, "arc": 2, "chapter": 3}
    level_label_map = {1: "卷", 2: "弧", 3: "章"}
    color_map = {1: "#8b5cf6", 2: "#06b6d4", 3: "#22c55e"}

    NODE_W = 280      # 节点宽度（含间距）
    VOL_GAP = 80      # 卷间距
    ARC_GAP = 30       # 弧纵向间距
    CH_GAP = 120       # 章纵向间距
    CH_COL_OFFSET = NODE_W + 40  # 章列相对弧列的 x 偏移
    Y_VOL = 0          # 卷 y
    Y_ARC_START = 160  # 弧 y 起点（卷下方）

    positions: dict[int, dict] = {}

    # 根节点（卷，无 parent 或 parent 不存在）
    roots = children_map.get(None, [])
    roots = [o for o in roots if (o.level or "volume") == "volume"] or roots

    # 分卷纵向布局：卷横排 → 弧纵向排 → 章在弧右侧纵向排
    # 每卷固定占 2 列宽（弧列 + 章列），不随弧数/章数增加变宽
    vol_x = 0
    for vol in roots:
        positions[vol.id] = {"x": vol_x, "y": Y_VOL}
        arcs = children_map.get(vol.id, [])
        # 若无弧，章直接挂卷下（章在卷右侧纵排）
        if not arcs:
            chapters = [o for o in outlines if getattr(o, "parent_id", None) == vol.id]
            for i, ch in enumerate(chapters):
                positions[ch.id] = {"x": vol_x, "y": Y_ARC_START + i * CH_GAP}
            vol_x += NODE_W + VOL_GAP
            continue

        arc_y = Y_ARC_START
        for arc in arcs:
            positions[arc.id] = {"x": vol_x, "y": arc_y}
            chapters = children_map.get(arc.id, [])
            # 章在弧右侧纵向排
            for i, ch in enumerate(chapters):
                positions[ch.id] = {"x": vol_x + CH_COL_OFFSET, "y": arc_y + i * CH_GAP}
            # 下一个弧 y = 当前弧 + max(章数*间距, 单间距) + 弧间距
            arc_y += max(len(chapters) * CH_GAP, CH_GAP) + ARC_GAP
        vol_x += NODE_W + CH_COL_OFFSET + VOL_GAP  # 卷宽 = 弧列 + 章列 + 间距

    # 构建节点和边
    nodes = []
    edges = []
    for o in outlines:
        if o.id not in positions:
            # 兜底：仍未定位的节点放最后
            positions[o.id] = {"x": vol_x, "y": 0}
            vol_x += NODE_W
        pos = positions[o.id]
        lvl = level_order.get(o.level or "chapter", 9)
        level_label = level_label_map.get(lvl, f"L{lvl}")
        color = color_map.get(lvl, "#94a3b8")
        node_id = f"outline_{o.id}"

        nodes.append({
            "id": node_id,
            "type": "dfOutline",
            "position": pos,
            "data": {
                "label": f"{level_label}{o.order}",
                "level": lvl,
                "level_label": level_label,
                "order": o.order,
                "title": o.title or "",
                "summary": (o.summary or "")[:200],
                "color": color,
            },
        })

        # 父子边
        parent_id = getattr(o, "parent_id", None)
        if parent_id and parent_id in id_to_outline:
            parent_lvl = level_order.get(id_to_outline[parent_id].level or "chapter", 9)
            p_color = color_map.get(parent_lvl, "#94a3b8")
            edges.append({
                "id": f"edge_{parent_id}_{o.id}",
                "source": f"outline_{parent_id}",
                "target": node_id,
                "type": "smoothstep",
                "style": {"stroke": p_color, "strokeWidth": 1.5},
            })

    return {"nodes": nodes, "edges": edges}


def _build_map_graph(project_id: int, db: Session, use_ai: bool = True) -> dict:
    """地图图谱：地点为节点，地点关系为边。

    布局策略（可视化融合 P3 混合方案）：
    1. 若地点已有用户设置的坐标(coord_x/coord_y 非0)，直接用真实坐标
    2. 若无坐标且 use_ai=True，走 LLM 语义约束 + 弹簧力学引擎布局
    3. 若 use_ai=False 或引擎失败，回退到按 importance 同心圆分层布局
    """
    from novel_agent.bible.models import Location, LocationRelationship

    locations = db.query(Location).filter(Location.project_id == project_id).all()
    rels = db.query(LocationRelationship).filter(LocationRelationship.project_id == project_id).all()

    if not locations:
        return {"nodes": [], "edges": []}

    # 检测是否有用户设置的真实坐标
    has_real_coords = any(loc.coord_x != 0 or loc.coord_y != 0 for loc in locations)

    if not has_real_coords and use_ai:
        # 尝试 AI 生成坐标
        ai_positions = _ai_layout_map(project_id, locations, rels, db)
        if ai_positions:
            positions = ai_positions
        else:
            # AI 失败回退：按 importance 同心圆分层
            positions = _map_fallback_layout(locations)
    elif has_real_coords:
        positions = {loc.id: {"x": loc.coord_x, "y": loc.coord_y} for loc in locations}
    else:
        positions = _map_fallback_layout(locations)

    type_color = {
        "city": "#06b6d4", "region": "#8b5cf6", "landmark": "#f59e0b",
        "secret": "#ec4899", "dungeon": "#ef4444", "other": "#94a3b8",
    }

    nodes = []
    for loc in locations:
        pos = positions.get(loc.id, {"x": 0, "y": 0})
        color = type_color.get(loc.type or "city", "#06b6d4")
        nodes.append({
            "id": f"loc_{loc.id}",
            "type": "dfLocation",
            "position": pos,
            "data": {
                "label": loc.name,
                "type": loc.type or "city",
                "description": loc.description or "",
                "parent_name": loc.parent_name or "",
                "importance": loc.importance or "",
                "color": color,
            },
        })

    # 构建地点名 → id 映射
    name_to_id = {loc.name: f"loc_{loc.id}" for loc in locations}

    # 边：地点关系
    edges = []
    rel_color = {
        "road": "#06b6d4", "adjacent": "#64748b", "contains": "#8b5cf6",
        "portal": "#ec4899", "warzone": "#ef4444",
    }
    for r in rels:
        src = name_to_id.get(r.source_location)
        tgt = name_to_id.get(r.target_location)
        if not src or not tgt:
            continue
        color = rel_color.get(r.relation_type or "road", "#64748b")
        is_adjacent = r.relation_type == "adjacent"
        edges.append({
            "id": f"edge_{r.id}",
            "source": src,
            "target": tgt,
            "label": str(r.distance) if r.distance else (r.relation_type or ""),
            "type": "smoothstep",
            "style": {"stroke": color, "strokeWidth": 1, "strokeDasharray": "5 5"} if is_adjacent else {"stroke": color, "strokeWidth": 2},
            "markerEnd": {"type": "arrowclosed", "color": color},
        })

    return {"nodes": nodes, "edges": edges}


def _map_fallback_layout(locations) -> dict:
    """地图回退布局：按 importance 同心圆分层。
    核心/首都放中心，重要地点第1圈，普通第2圈，次要第3圈。
    """
    importance_layer = {
        "核心": 0, "首都": 0, "主角": 0, "顶级": 0,
        "重要": 1, "主要": 1,
        "普通": 2, "中等": 2,
        "次要": 3, "边缘": 3, "偏远": 3,
    }

    def layer_fn(loc):
        imp = (loc.importance or "").strip()
        return importance_layer.get(imp, 2)

    pos_list = _layered_circular_layout(locations, layer_fn, max_layers=4, cx=600, cy=500)
    return {loc.id: pos_list[i] for i, loc in enumerate(locations)}


def _ai_layout_map(project_id: int, locations, rels, db: Session) -> dict | None:
    """地图布局：LLM 语义约束 + 引擎精确布局（可视化融合 P3 混合方案）。

    LLM 只输出**方位语义**（每个地点的 direction 相对方位 + relative_to 相对参照），
    不输出精确坐标——一次调用、token 省、失败可回退。
    引擎（novel_agent.geo.map_layout）把语义转成弹簧力学模型迭代求解坐标。

    Returns:
        {location_id: {x, y}} 或 None（LLM 失败时）
    """
    import asyncio
    import json as _json
    from dataclasses import replace
    from novel_agent.config import load_config
    from novel_agent.geo.map_layout import layout_map, parse_semantic_hints
    from novel_agent.llm.client import LLMClient

    # 1. LLM 一次性生成语义约束（低成本；短超时，失败快速回退到纯引擎）
    semantic_hints: dict = {}
    try:
        cfg = load_config()
        # 地图方位只是轻量语义，给 30s 超时，避免网络异常把整页卡死
        hint_cfg = replace(cfg.llm, timeout=30.0)
        client = LLMClient(hint_cfg)

        loc_list = [
            {
                "id": loc.id,
                "name": loc.name,
                "type": loc.type or "city",
                "description": (loc.description or "")[:120],
                "parent_name": loc.parent_name or "",
                "importance": loc.importance or "",
            }
            for loc in locations
        ]
        rel_list = [
            {"source": r.source_location, "target": r.target_location,
             "relation_type": r.relation_type or "road"}
            for r in rels
        ]

        system_prompt = """你是小说世界观地图方位设计师。根据地点设定与关系，只输出每个地点的**相对方位**语义，不输出任何坐标。

要求：
1. direction 取值：north / south / east / west / northeast / northwest / southeast / southwest / center（相对地图整体）
2. 天界/仙界类地点 → north；幽冥/地府类 → south；海底/龙宫类 → 可 south 或 relative_to 参照
3. 有父子关系的地点，子地点 direction=center 并用 relative_to 指向父地点名
4. 相邻(adjacent)地点 direction 相近；传送(portal)地点可相反方向
5. 重要地点(importance=核心/首都/主角) → center
6. 无法判断的 → center

只返回 JSON 数组，格式：[{"name": "地点名", "direction": "north", "relative_to": "参照地点名（可省略）"}, ...]
不要输出任何其他内容、解释或 markdown 代码块标记。"""

        user_prompt = f"""## 地点清单（{len(loc_list)} 个）
{_json.dumps(loc_list, ensure_ascii=False, indent=2)}

## 地点关系（{len(rel_list)} 条）
{_json.dumps(rel_list, ensure_ascii=False, indent=2) if rel_list else "（暂无关系）"}

请为每个地点生成相对方位语义，只返回 JSON 数组。"""

        loop = asyncio.new_event_loop()
        try:
            content = loop.run_until_complete(
                client.generate(user_prompt, system=system_prompt, max_tokens=2000, temperature=0.3, thinking=False, node_name="map_layout_semantic")
            )
        finally:
            loop.close()

        semantic_hints = parse_semantic_hints(content)
        logger.info("AI 地图语义约束生成 %d/%d 个", len(semantic_hints), len(locations))
    except Exception as e:
        logger.warning("AI 地图语义约束生成失败，走纯引擎布局: %s: %s", type(e).__name__, e)

    # 2. 引擎（弹簧力学）精确布局：有语义当锚点，无语义纯算法
    try:
        loc_dicts = [
            {
                "id": loc.id,
                "name": loc.name,
                "type": loc.type or "city",
                "layer": getattr(loc, "layer", "") or "surface",
                "parent_name": loc.parent_name or "",
                "importance": loc.importance or "",
            }
            for loc in locations
        ]
        rel_dicts = [
            {"source": r.source_location, "target": r.target_location,
             "relation_type": r.relation_type or "road"}
            for r in rels
        ]
        positions = layout_map(loc_dicts, rel_dicts, hints=semantic_hints)
        logger.info("地图引擎布局完成 %d 个地点", len(positions))
        return positions if positions else None
    except Exception as e:
        logger.warning("地图引擎布局失败: %s: %s", type(e).__name__, e)
        return None


# ===== 地点 CRUD =====
def _location_dict(loc) -> dict:
    return {
        "id": loc.id,
        "project_id": loc.project_id,
        "name": loc.name,
        "type": loc.type,
        "description": loc.description,
        "parent_name": loc.parent_name,
        "coord_x": loc.coord_x,
        "coord_y": loc.coord_y,
        "importance": loc.importance,
        "tier": loc.tier or "",
        "layer": loc.layer or "surface",
    }


@router.get("/{project_id}/locations")
def list_locations(project_id: int, db: Session = Depends(get_db)):
    from novel_agent.bible.models import Location
    items = db.query(Location).filter(Location.project_id == project_id).order_by(Location.importance.desc(), Location.name).all()
    return [_location_dict(loc) for loc in items]


@router.post("/{project_id}/locations")
def create_location(project_id: int, data: LocationInput, db: Session = Depends(get_db)):
    from novel_agent.bible.models import Location
    if not data.name.strip():
        raise HTTPException(400, "地点名称不能为空")
    existing = db.query(Location).filter(Location.project_id == project_id, Location.name == data.name.strip()).first()
    if existing:
        raise HTTPException(409, "地点名称已存在")
    loc = Location(
        project_id=project_id,
        name=data.name.strip(),
        type=data.type,
        description=data.description,
        parent_name=data.parent_name,
        coord_x=data.coord_x,
        coord_y=data.coord_y,
        importance=data.importance,
        tier=data.tier,
        layer=data.layer,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return _location_dict(loc)


@router.put("/{project_id}/locations/{location_id}")
def update_location(project_id: int, location_id: int, data: LocationInput, db: Session = Depends(get_db)):
    from novel_agent.bible.models import Location
    loc = db.query(Location).filter(Location.project_id == project_id, Location.id == location_id).first()
    if not loc:
        raise HTTPException(404, "地点不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(loc, k, v)
    db.commit()
    db.refresh(loc)
    return _location_dict(loc)


@router.delete("/{project_id}/locations/{location_id}")
def delete_location(project_id: int, location_id: int, db: Session = Depends(get_db)):
    from novel_agent.bible.models import Location
    loc = db.query(Location).filter(Location.project_id == project_id, Location.id == location_id).first()
    if not loc:
        raise HTTPException(404, "地点不存在")
    db.delete(loc)
    db.commit()
    return {"deleted": True}


@router.post("/{project_id}/locations/auto-classify")
def auto_classify_locations(project_id: int, db: Session = Depends(get_db)):
    """自动推断所有地点的 tier 和 layer，仅填充空值，不覆盖用户已设置的值。"""
    from novel_agent.bible.models import Location
    from novel_agent.bible.world_structure import classify_tier, classify_layer

    items = db.query(Location).filter(Location.project_id == project_id).all()
    updated = 0
    for loc in items:
        changed = False
        if not loc.tier:
            loc.tier = classify_tier(loc.name)
            changed = True
        if not loc.layer or loc.layer == "surface":
            layer = classify_layer(loc.name, loc.description or "")
            if layer != "surface":
                loc.layer = layer
                changed = True
        if changed:
            updated += 1
    if updated:
        db.commit()
    return {"updated": updated, "total": len(items)}


@router.get("/{project_id}/locations/validate-hierarchy")
def validate_location_hierarchy(project_id: int, db: Session = Depends(get_db)):
    """校验地点层级：父地点存在性、循环引用、tier 跨度过大。"""
    from novel_agent.bible.models import Location
    from novel_agent.bible.world_structure import validate_hierarchy

    items = db.query(Location).filter(Location.project_id == project_id).all()
    locations = [_location_dict(loc) for loc in items]
    issues = validate_hierarchy(locations)
    return {"issues": issues, "total": len(locations), "error_count": sum(1 for i in issues if i["severity"] == "error"), "warning_count": sum(1 for i in issues if i["severity"] == "warning")}


# ===== 地点关系 CRUD =====
def _loc_rel_dict(r) -> dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "source_location": r.source_location,
        "target_location": r.target_location,
        "relation_type": r.relation_type,
        "distance": r.distance,
        "description": r.description,
    }


@router.get("/{project_id}/location-relationships")
def list_location_relationships(project_id: int, db: Session = Depends(get_db)):
    from novel_agent.bible.models import LocationRelationship
    items = db.query(LocationRelationship).filter(LocationRelationship.project_id == project_id).all()
    return [_loc_rel_dict(r) for r in items]


@router.post("/{project_id}/location-relationships")
def create_location_relationship(project_id: int, data: LocationRelationshipInput, db: Session = Depends(get_db)):
    from novel_agent.bible.models import LocationRelationship
    if not data.source_location or not data.target_location:
        raise HTTPException(400, "源地点和目标地点不能为空")
    r = LocationRelationship(
        project_id=project_id,
        source_location=data.source_location,
        target_location=data.target_location,
        relation_type=data.relation_type,
        distance=data.distance,
        description=data.description,
    )
    db.add(r)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "关系已存在（重复）")
    db.refresh(r)
    return _loc_rel_dict(r)


@router.put("/{project_id}/location-relationships/{rel_id}")
def update_location_relationship(project_id: int, rel_id: int, data: LocationRelationshipInput, db: Session = Depends(get_db)):
    from novel_agent.bible.models import LocationRelationship
    r = db.query(LocationRelationship).filter(LocationRelationship.project_id == project_id, LocationRelationship.id == rel_id).first()
    if not r:
        raise HTTPException(404, "地点关系不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return _loc_rel_dict(r)


@router.delete("/{project_id}/location-relationships/{rel_id}")
def delete_location_relationship(project_id: int, rel_id: int, db: Session = Depends(get_db)):
    from novel_agent.bible.models import LocationRelationship
    r = db.query(LocationRelationship).filter(LocationRelationship.project_id == project_id, LocationRelationship.id == rel_id).first()
    if not r:
        raise HTTPException(404, "地点关系不存在")
    db.delete(r)
    db.commit()
    return {"deleted": True}
