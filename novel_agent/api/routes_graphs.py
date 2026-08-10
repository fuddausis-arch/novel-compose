"""小说内容图谱 API：CRUD + 一键生成（人物/势力/伏笔/章节）。

图谱数据存 graphs 表，graph_data 字段存 ReactFlow 的 {nodes, edges} JSON。
一键生成从圣经数据库拉数据，自动布局后返回图结构。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Graph
from novel_agent.config import load_config
from novel_agent.graphs.version import is_graph_dirty, mark_graph_generated

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
    tier: str = ""               # continent/kingdom/region/city/town/district/site/dungeon/landmark/other
    layer: str = "surface"       # surface/celestial/underworld/underwater/realm/other
    ruler: str = ""              # 城主/掌管者（角色名，多个用顿号分隔）
    plot_role: str = ""          # 剧情作用：该地点在剧情中的定位
    unlocked_chapter: int = 0    # 剧情解锁章节：0=未解锁，>0=第 N 章起已解锁


class LocationRelationshipInput(BaseModel):
    source_location: str
    target_location: str
    relation_type: str = "road"  # road/adjacent/contains/portal/warzone
    distance: str = ""
    description: str = ""


class AiGenerateMapRequest(BaseModel):
    max_new: int = 15  # AI 新增地点数量上限


# ===== 序列化 =====
def _graph_dict(g: Graph) -> dict:
    # 脏标记：剧情数据（写章/大纲/角色等）比该图谱新 → dirty=True（前端提示"有更新"）
    dirty = False
    try:
        dirty = is_graph_dirty(g.project_id, g.id)
    except Exception:
        pass
    return {
        "id": g.id,
        "project_id": g.project_id,
        "name": g.name,
        "graph_type": g.graph_type,
        "description": g.description,
        "graph_data": g.graph_data or {"nodes": [], "edges": []},
        "is_auto": g.is_auto,
        "dirty": dirty,
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
    # 新建即视为"当前内容版本下已刷新"（刚生成/手动建，不含旧快照）
    mark_graph_generated(project_id, g.id)
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
    # 保存即标记该图已对齐当前内容版本（前端"一键刷新"后调用此接口清除脏标记）
    mark_graph_generated(project_id, g.id)
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

    布局策略（层级优先，可视化融合）：
    1. 若地点已有用户设置的坐标(coord_x/coord_y 非0)，直接用真实坐标
    2. 否则走**层级树布局**：大陆/主城在中心，附属城/街区/建筑逐层环绕父级
       （层级感最直观，符合"主城大、卫星城围一圈、街道内嵌"的预期）
    3. 层级树不可用（无父链）时，走 LLM 语义约束 + 弹簧力学引擎布局
    4. 引擎失败回退到按 importance 同心圆分层布局
    """
    from novel_agent.bible.models import Location, LocationRelationship, Character, TruthEvent

    locations = db.query(Location).filter(Location.project_id == project_id).all()
    rels = db.query(LocationRelationship).filter(LocationRelationship.project_id == project_id).all()

    if not locations:
        return {"nodes": [], "edges": []}

    # 检测是否有用户设置的真实坐标
    has_real_coords = any(loc.coord_x != 0 or loc.coord_y != 0 for loc in locations)

    if has_real_coords:
        positions = {loc.id: {"x": loc.coord_x, "y": loc.coord_y} for loc in locations}
    else:
        # 1) 层级树布局优先（真正成树且孤立地点少时才有意义）
        positions = _hierarchical_map_layout(locations)
        if not positions:
            # 2) 力导向引擎（纯算法、零 LLM、天然分散，父子地点强吸引）
            positions = _engine_map_layout(locations)
        if not positions and use_ai:
            # 3) LLM 语义约束 + 弹簧力学
            positions = _ai_layout_map(project_id, locations, rels, db)
        if not positions:
            # 4) 兜底：importance 同心圆
            positions = _map_fallback_layout(locations)

    type_color = {
        "city": "#06b6d4", "region": "#8b5cf6", "landmark": "#f59e0b",
        "secret": "#ec4899", "dungeon": "#ef4444", "other": "#94a3b8",
    }

    # 关联数据：角色所在地 + 事件发生地（让地图与其他数据联动）
    chars = db.query(Character).filter(Character.project_id == project_id).all()
    loc_residents: dict[str, list[str]] = {}
    for c in chars:
        cl = (c.current_location or "").strip()
        if cl:
            loc_residents.setdefault(cl, []).append(c.name)
    tevents = db.query(TruthEvent).filter(TruthEvent.project_id == project_id).all()
    loc_event_count: dict[str, int] = {}
    for te in tevents:
        p = te.payload if isinstance(te.payload, dict) else {}
        pl = str(p.get("location") or p.get("place") or "").strip()
        if pl:
            loc_event_count[pl] = loc_event_count.get(pl, 0) + 1

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
                "tier": loc.tier or "",
                "ruler": loc.ruler or "",
                "plot_role": loc.plot_role or "",
                "unlocked_chapter": loc.unlocked_chapter or 0,
                "color": color,
                "residents": loc_residents.get(loc.name, [])[:20],
                "event_count": loc_event_count.get(loc.name, 0),
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

    # 自动补边：上级地点 → 包含关系（无需手动维护）
    # 优先用库里的 parent_name；未填时用名称前缀推断父子（旧数据也能立即连线）
    parent_map = _infer_parent_names({loc.name for loc in locations})
    seen = {(e["source"], e["target"]) for e in edges}
    for loc in locations:
        parent = (loc.parent_name or "").strip() or parent_map.get(loc.name, "")
        if not parent:
            continue
        parent_id = name_to_id.get(parent)
        child_id = name_to_id.get(loc.name)
        if not parent_id or not child_id or parent_id == child_id:
            continue
        if (parent_id, child_id) in seen:
            continue
        edges.append({
            "id": f"auto_parent_{loc.id}",
            "source": parent_id,
            "target": child_id,
            "label": "包含",
            "type": "smoothstep",
            "style": {"stroke": "#8b5cf6", "strokeWidth": 1.5, "strokeDasharray": "4 4"},
        })
        seen.add((parent_id, child_id))

    return {"nodes": nodes, "edges": edges}


def _hierarchical_map_layout(locations) -> dict | None:
    """层级树布局：大陆/主城在中心，子级（附属城/街区/建筑）环绕父级分布。

    以 parent_name 构建树，递归放置：
    - 根（无父地点）放最内圈中心
    - 每个父节点的子节点均匀分布在以父为中心的圆周上
    - 环绕半径随层级深度递增，保证不同层级在地理上分离
    返回 {location_id: {x, y}}；无父链（全部孤立）时返回 None 走原布局。
    """
    import math

    name_to_loc = {loc.name: loc for loc in locations}
    children: dict[str, list] = {}
    for loc in locations:
        p = (loc.parent_name or "").strip()
        if p and p in name_to_loc:
            children.setdefault(p, []).append(loc)

    # 根：无父 或 父地点不存在于清单（孤儿地点也当根，避免丢节点）
    roots = [loc for loc in locations
             if not (loc.parent_name or "").strip() or loc.parent_name not in name_to_loc]
    if not roots:
        return None

    # 有没有真正连成树的子链？没有则退回 None（纯并列地点用弹簧布局更合适）
    if not children:
        return None

    # 孤立地点过多时层级树无意义：所有根铺一个大圆仍会挤成一团（节点宽240px），
    # 退回力导向引擎让 61+ 个节点摊开到整个画布。
    if len(roots) > 6:
        return None

    positions: dict[int, dict] = {}

    def place(loc, cx, cy, depth: int):
        positions[loc.id] = {"x": round(cx), "y": round(cy)}
        kids = children.get(loc.name, [])
        if not kids:
            return
        n = len(kids)
        # 环绕半径：随深度 + 子节点数自适应，保证子节点不糊在一起
        # 每个子节点至少占 260px 圆周弧长（节点宽 240 + 间距 20）
        r = max(150 + depth * 90, math.ceil(n * 260 / (2 * math.pi)))
        for i, k in enumerate(kids):
            a = 2 * math.pi * i / n - math.pi / 2  # 从正上方开始顺时针
            place(k, cx + r * math.cos(a), cy + r * math.sin(a), depth + 1)

    if len(roots) == 1:
        place(roots[0], 0, 0, 0)
    else:
        # 多个根：根之间按数量自适应分布（同样保证圆周弧长 ≥ 260px）
        n = len(roots)
        r_root = max(400, math.ceil(n * 260 / (2 * math.pi)))
        for i, r in enumerate(roots):
            a = 2 * math.pi * i / n
            place(r, r_root * math.cos(a), r_root * math.sin(a), 0)

    # 偏移到正坐标（+边距），避免负坐标
    xs = [p["x"] for p in positions.values()]
    ys = [p["y"] for p in positions.values()]
    if not xs:
        return None
    min_x, min_y = min(xs), min(ys)
    for p in positions.values():
        p["x"] = p["x"] - min_x + 120
        p["y"] = p["y"] - min_y + 120
    return positions


def _engine_map_layout(locations) -> dict:
    """力导向引擎布局：纯算法、零 LLM 调用，节点天然分散不重叠。

    把 parent_name 转成 contains 强吸引边（子地点环绕父地点），
    画布大小随节点数自适应（每个节点预留约 56000px²，避免放大后仍密集）。
    对应计划书：孤立地点多/层级树不可用时的首选布局。
    """
    import math
    from novel_agent.geo.map_layout import layout_map

    locs = [
        {"id": l.id, "name": l.name, "type": l.type, "layer": l.layer or "",
         "parent_name": l.parent_name or "", "importance": l.importance or ""}
        for l in locations
    ]
    rels = []
    for l in locations:
        p = (l.parent_name or "").strip()
        if p and p != l.name:
            rels.append({"source": l.name, "target": p, "relation_type": "contains"})

    # 画布面积随节点数自适应（16:9）；每节点 64000px² 保证平均间距 >240px
    area = max(len(locations) * 64000, 2000 * 1400)
    width = max(1800, int(math.sqrt(area * 16 / 9)))
    height = max(1300, int(width * 9 / 16))
    positions = layout_map(locs, rels, hints=None, width=width, height=height, iterations=140)
    if not positions:
        return {}
    # 平移到正坐标
    xs = [p["x"] for p in positions.values()]
    ys = [p["y"] for p in positions.values()]
    min_x, min_y = min(xs), min(ys)
    return {lid: {"x": p["x"] - min_x + 120, "y": p["y"] - min_y + 120}
            for lid, p in positions.items()}


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
        "ruler": loc.ruler or "",
        "plot_role": loc.plot_role or "",
        "unlocked_chapter": loc.unlocked_chapter or 0,
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
        ruler=data.ruler,
        plot_role=data.plot_role,
        unlocked_chapter=data.unlocked_chapter,
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


def _norm_loc_item(item) -> dict:
    """LLM 输出字段容错：key 小写去空格下划线 + 字段别名归一。

    真实 LLM 经常变体：name→value/location/place/location_id/aliases、
    description→descriptiion/desc、is_new/is_existing 是字符串 "true"。
    这里统一成标准字段，并把 is_new 反转成 is_existing。
    """
    norm: dict = {}
    if not isinstance(item, dict):
        return norm
    for k, v in item.items():
        key = str(k).lower().replace(" ", "").replace("_", "")
        if key not in norm or not norm[key]:
            norm[key] = v
    # 名称别名（location_id/aliases 常见于 LLM 输出的超全字段版）
    if not str(norm.get("name") or "").strip():
        for alias in ("value", "location", "place", "placename", "locationid", "id", "alias", "aliases"):
            v = norm.get(alias)
            if isinstance(v, list):
                v = v[0] if v else ""
            if str(v or "").strip():
                norm["name"] = v
                break
    # 描述别名
    if "description" not in norm or not str(norm.get("description") or "").strip():
        norm["description"] = norm.get("descriptiion") or norm.get("desc") or ""
    # 已有/新增布尔化：is_new 取反成 is_existing（兼容字符串 "true"/"1"/"是"）
    if "is_new" in norm:
        v = norm["is_new"]
        is_new = str(v).strip().lower() in ("true", "1", "yes", "是") if isinstance(v, str) else bool(v)
        norm["is_existing"] = not is_new
    elif "is_existing" in norm:
        v = norm["is_existing"]
        norm["is_existing"] = str(v).strip().lower() in ("true", "1", "yes", "是", "已有", "existing") if isinstance(v, str) else bool(v)
    # 关系字段别名：from/to、rel
    if "source" not in norm or not norm.get("source"):
        norm["source"] = norm.get("from", "")
    if "target" not in norm or not norm.get("target"):
        norm["target"] = norm.get("to", "")
    if not norm.get("relation_type"):
        norm["relation_type"] = norm.get("rel", "")
    # 剧情作用别名：plot_role → plotrole 已归一，取回标准字段名
    if "plotrole" in norm and "plot_role" not in norm:
        norm["plot_role"] = norm.pop("plotrole")
    # 类型枚举归一：LLM 常填错/填自定义词，非法值归 other
    _LOC_TYPES = ("city", "region", "landmark", "secret", "dungeon", "other")
    t = str(norm.get("type") or "").strip().lower()
    if t and t not in _LOC_TYPES:
        norm["type"] = "other"
    return norm


def _extract_json_anywhere(raw: str) -> dict | None:
    """parse_json_safe 失败时的兜底：用栈扫描定位第一个完整闭合的 {…} 再 json.loads。

    处理字符串内的 { } 与转义，避免 LLM 输出尾部残留 markdown/解释导致解析失败。
    """
    if not raw:
        return None
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        return None
    return None


# 合理地点名最大长度（超过即判定混入了描述，需清洗）
_LOCATION_NAME_MAX = 30

# 层级中文值 → tier 枚举（层级从大到小，dict 顺序即层级序）
# continent 大陆 → region 区域/国家 → city 城市/主城 → town 附属城/卫星城
# → district 街区/街道 → site 建筑/地标 → dungeon 秘境/副本
_TIER_ZH_MAP: dict[str, str] = {
    "大陆": "continent", "世界": "continent",
    "区域": "region", "国家": "kingdom", "帝国": "kingdom",
    "城市": "city", "主城": "city", "都城": "city", "王城": "city",
    "附属城": "town", "附属城镇": "town", "卫星城": "town", "城镇": "town", "镇": "town",
    "街区": "district", "街道": "district", "城区": "district",
    "建筑": "site", "地标": "landmark", "遗迹": "landmark",
    "秘境": "dungeon", "副本": "dungeon", "地下城": "dungeon",
}

# 层级权重（用于布局/大小/校验）：数值越小层级越大
_TIER_ORDER: dict[str, int] = {
    "continent": 0, "kingdom": 0, "region": 1,
    "city": 2, "town": 3, "district": 4, "site": 5,
    "dungeon": 6, "landmark": 6, "other": 7,
}

def _tier_weight(tier: str) -> int:
    """层级权重：未识别层级返回 7（最小）。"""
    return _TIER_ORDER.get((tier or "").strip().lower(), 7)


def _clean_location_name(raw_name: str) -> str:
    """清洗 AI 输出的地点名。

    LLM 不按格式输出时会把整段描述当名称（几十上百字）。合理地点名很短，
    超长说明混入了描述——尝试在常见描述起点截断，仍超长则返回空（调用方丢弃）。
    """
    name = (raw_name or "").strip().strip("|")
    if not name:
        return ""
    if len(name) <= _LOCATION_NAME_MAX:
        return name
    # 常见描述起始词/标点：优先从句点、逗号断开
    for sep in ("，", "。", "；", "位于", "坐落", "一座", "一处", "一栋",
                "这里", "据说", "门口", "距离"):
        idx = name.find(sep, 2)
        if idx != -1:
            cand = name[:idx].strip()
            if cand and len(cand) <= _LOCATION_NAME_MAX:
                return cand
    return ""  # 无法截断 → 丢弃该地点（宁缺毋滥）


def _infer_parent_names(names: set[str]) -> dict[str, str]:
    """自动父子推断：地点名以另一地点名为前缀且剩余部分像子场所时，推断父级。

    例：'灰烬农场带边缘哨站' → 父 '灰烬农场带'；'蜂巢公寓迷宫入口' → 父 '蜂巢公寓迷宫'。
    长名优先，避免链式误判。Returns: {地点名: 父地点名}
    """
    result: dict[str, str] = {}
    name_list = sorted(names, key=len, reverse=True)
    for name in name_list:
        if not name or name in result:
            continue
        best = ""
        for other in names:
            if not other or other == name or len(other) >= len(name) or len(other) < 2:
                continue
            # 真前缀且差异 >=2 字（避免"风语平原磨坊镇"反过来匹配"风语平原"这种合法父级之外的误配）
            if name.startswith(other) and len(name) - len(other) >= 2:
                if len(other) > len(best):
                    best = other
        if best:
            result[name] = best
    return result


def _parse_location_lines(raw: str) -> list[dict]:
    """文本行格式兜底：每行一个地点。

    新格式（层级化）：名称|层级|类型|上级|城主|剧情作用|描述
      层级取中文直观值：大陆/区域/国家/城市/附属城/卫星城/街区/街道/建筑/地标/秘境/副本
      例：曙光城|城市|city|曙光大陆|白夜|主角出生地|废土最大的幸存者聚居地
    旧格式兼容：名称|类型|重要性|上级|描述（第 2 段是英文类型枚举时按旧格式解析）

    宽松解析：行内有 | 取对应段；没有 | 则整行当作名称（超长会清洗丢弃）。
    """
    items: list[dict] = []
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("-•*0123456789.、)）")
        if not line:
            continue
        if line.startswith("#") or line.startswith("地点") or line.startswith("关系"):
            continue
        # 过滤 AI 常见废话行（提示语/总结/格式说明），避免被当成地点名
        if line.startswith(("请", "以下", "以上", "（", "(", "注", "说明", "根据", "为", "如果")):
            continue
        # 跳过 markdown 代码块围栏与 JSON 残留行
        if line.startswith("```") or line.startswith("{") or line.startswith("}"):
            continue
        parts = [p.strip() for p in line.split("|")]
        name = _clean_location_name(parts[0] if parts else "")
        if not name:
            continue
        # 新格式标志：行内任意位置出现中文层级词（LLM 常因空段/思考泄漏导致字段错位，
        # 只要找到层级词就按 新格式 解析：去空段后依次 name/tier/type/parent/ruler/plot_role/desc）
        tier_idx = -1
        for i, p in enumerate(parts):
            if p in _TIER_ZH_MAP:
                tier_idx = i
                break
        if tier_idx != -1:
            compact = [parts[0]] + [p for p in parts[tier_idx:] if p]
            seq = compact
            items.append({
                "name": name,
                "tier": _TIER_ZH_MAP[seq[1]] if len(seq) > 1 else "",
                "type": seq[2] if len(seq) > 2 else "",
                "parent_name": seq[3] if len(seq) > 3 else "",
                "ruler": seq[4] if len(seq) > 4 else "",
                "plot_role": seq[5] if len(seq) > 5 else "",
                "importance": "",
                "description": "".join(seq[6:]) if len(seq) > 6 else "",
            })
        else:
            # 旧格式：名称|类型|重要性|上级|描述
            items.append({
                "name": name,
                "type": parts[1] if len(parts) > 1 else "",
                "importance": parts[2] if len(parts) > 2 else "",
                "parent_name": parts[3] if len(parts) > 3 else "",
                "tier": "",
                "ruler": "",
                "plot_role": "",
                "description": "".join(parts[4:]) if len(parts) > 4 else "",
            })
    return items


def _parse_relation_lines(raw: str) -> list[dict]:
    """文本行关系兜底：每行 关系|源地点|目标地点|类型|距离。

    AI 生成地图时若未输出 JSON relationships，会按此格式输出关系行。
    """
    rels: list[dict] = []
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("-•*0123456789.、)）")
        if not line or not line.startswith("关系"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        src, tgt = parts[1], parts[2]
        rtype = (parts[3] if len(parts) > 3 else "road").strip() or "road"
        dist = parts[4] if len(parts) > 4 else ""
        if src and tgt and src != tgt:
            rels.append({"source": src, "target": tgt, "relation_type": rtype, "distance": dist})
    return rels


@router.post("/{project_id}/locations/ai-generate-map")
async def ai_generate_map(project_id: int, data: AiGenerateMapRequest,
                          db: Session = Depends(get_db)):
    """SSE：AI 根据当前资产设定 + bishu-novel 世界观文件，智能合并生成世界地图。

    读取：world_settings（六维设定）、已有地点/关系、势力（含地盘）、副本、
    项目工作区 meta/*.md 世界观文件（bishu-novel 产物，存在才读）。
    LLM 输出智能合并方案：
    - keep：已有地点只补空字段（type/tier/layer/importance/parent/description），不覆盖已有内容
    - new：与世界观一致的新地点（数量 ≤ max_new，与已有地点不重名）
    - relationships：基于最终地点集的连接关系
    写库后前端重新走 auto-generate 出图谱（布局仍由 LLM 语义约束 + 弹簧力学引擎负责）。

    事件类型：
    - gen_stage {stage}
    - gen_done {created, updated, relations, total}
    - error {error}
    """
    from novel_agent.bible.models import (
        Faction, Instance, Location, LocationRelationship, WorldSetting,
    )
    from novel_agent.llm.client import LLMClient
    from novel_agent.utils.json_output import parse_json_safe

    max_new = max(1, min(data.max_new or 15, 60))

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        async def _run():
            client = None
            try:
                cfg = load_config()

                # ---- 1. 读取资产 ----
                await emit({"type": "gen_stage", "stage": "读取项目资产与世界观..."})
                world_settings = db.query(WorldSetting).filter(WorldSetting.project_id == project_id).all()
                locations = db.query(Location).filter(Location.project_id == project_id).all()
                rels = db.query(LocationRelationship).filter(LocationRelationship.project_id == project_id).all()
                factions = db.query(Faction).filter(Faction.project_id == project_id).all()
                instances = db.query(Instance).filter(Instance.project_id == project_id).all()

                ws_text = "\n".join(
                    f"【{s.category or ''}{'/' + s.dimension if s.dimension else ''}】{s.title}: {s.content}"
                    for s in world_settings if (s.content or "").strip()
                )[:8000]
                loc_list = [{
                    "name": l.name, "type": l.type or "city", "tier": l.tier or "",
                    "layer": l.layer or "surface", "importance": l.importance or "",
                    "parent_name": l.parent_name or "", "description": (l.description or "")[:200],
                } for l in locations]
                rel_list = [{
                    "source": r.source_location, "target": r.target_location,
                    "relation_type": r.relation_type or "road", "distance": r.distance or "",
                } for r in rels]
                fac_list = [{"name": f.name, "description": (f.description or "")[:200]} for f in factions]
                inst_list = [{"name": i.name, "description": (i.description or "")[:150]} for i in instances]

                # bishu-novel 世界观文件（跑过 MVP 工作流才有 meta/，存在才读，缺失不报错）
                meta_dir = cfg.project_data_dir / "projects" / str(project_id) / "meta"
                bishu_text = ""
                if meta_dir.exists():
                    for p in sorted(meta_dir.glob("*.md")):
                        try:
                            bishu_text += f"\n===== {p.stem} =====\n" + p.read_text(encoding="utf-8", errors="ignore")[:2000]
                        except OSError:
                            continue
                    bishu_text = bishu_text[:6000]

                # ---- 2. LLM 智能合并 ----
                await emit({"type": "gen_stage",
                            "stage": f"AI 生成世界地图中（已有 {len(locations)} 个地点）..."})
                client = LLMClient(cfg.get_agent_llm("auditor"))

                system_prompt = f"""你是小说世界观地图设计师。根据项目已有设定与资产，设计**新增**的世界地图地点（已有地点不重复列出）。

要求：
1. 世界地图必须按**层级**组织，从上到下：大陆(continent) → 区域/国家(region/kingdom) → 主城/城市(city) → 附属城/卫星城(town) → 街区/街道(district) → 建筑/地标(site)，另有秘境/副本(dungeon)
2. 每个新地点占一行，用 | 分隔，**严格恰好 7 段**（没有的内容就留空段，| 分隔符保留）：
   名称|层级|类型|上级地点|城主|剧情作用|描述
   例：曙光城|城市|city|曙光大陆|白夜|主角出生地，第一卷核心舞台|废土最大的幸存者聚居地
   例：城东集市区|街区|region|曙光城|无|第一章主角活动区域|贩卖废土物资的市集
3. 层级取中文值：大陆/区域/国家/城市/附属城/卫星城/街区/街道/建筑/地标/秘境/副本（无合适层级就用"区域"）
4. 类型取：city/region/landmark/secret/dungeon/other
5. 上级地点必须来自「已有地点」清单或本批新增的上级地点名；街道/建筑必须挂在城市/附属城下，附属城必须挂在城市/大陆下，禁止孤立
6. 城主填该地点的掌管角色名（必须来自项目已有角色或资产设定），**每一项都必须填**：有掌管者填角色名，没有就填"无"，禁止填描述性文字
7. 剧情作用写清楚该地点在剧情中的定位（如"主角出生地""第X卷决战地""补给中转站"），**每一项都必须填**，没有特别作用填"无"
8. 新地点数量 ≤ {max_new}
9. 在所有地点行之后，**必须输出至少 5 条关系**，每行格式：关系|源地点|目标地点|类型|距离说明
   类型取：road（道路）/ adjacent（相邻）/ contains（包含）/ portal（传送门）
   父级与子级之间必须输出 contains 关系；新地点与已有地点之间也尽量连 road/adjacent，让地图连线丰富
10. 只输出地点行和关系行，不要输出 JSON、不要编号、不要任何解释或 markdown
11. 直接给出最终答案，禁止在输出中思考、自我修正、重写或添加任何说明文字（一旦开始修正请整行重写后再输出）

示例：
曙光城|城市|city|曙光大陆|白夜|主角出生地，第一卷核心舞台|废土最大的幸存者聚居地
城东集市区|街区|region|曙光城|无|第一章主角活动区域|贩卖废土物资的市集
城西工业区|街区|region|曙光城|白夜|主角发现线索的地方|废旧机械回收厂聚集地
曙光港|附属城|city|曙光城|郑铁|主角出海必经地|曙光城唯一对外港口
地下黑市|建筑|site|城西工业区|无|主角获取情报的灰色地带|见不得光的交易场所
关系|曙光城|曙光港|contains|-
关系|曙光城|城东集市区|contains|-
关系|曙光城|城西工业区|contains|-
关系|城西工业区|地下黑市|contains|-
关系|城东集市区|城西工业区|road|半小时路程"""

                user_prompt = f"""## 世界观设定（world_settings）
{ws_text if ws_text else "（项目暂无结构化世界观设定）"}

## bishu-novel 世界观文件
{bishu_text if bishu_text else "（无，可忽略）"}

## 已有地点（{len(loc_list)} 个）
{json.dumps(loc_list, ensure_ascii=False, indent=2) if loc_list else "（无）"}

## 已有地点关系（{len(rel_list)} 条）
{json.dumps(rel_list, ensure_ascii=False, indent=2) if rel_list else "（无）"}

## 势力（{len(fac_list)} 个）
{json.dumps(fac_list, ensure_ascii=False, indent=2) if fac_list else "（无）"}

## 副本/秘境（{len(inst_list)} 个）
{json.dumps(inst_list, ensure_ascii=False, indent=2) if inst_list else "（无）"}

请按系统要求输出新增地点方案：每行一个地点（名称|层级|类型|上级地点|城主|剧情作用|描述，新地点不超过 {max_new} 个），地点行之后输出关系行（关系|源地点|目标地点|类型|距离）。"""

                content = await client.generate(
                    user_prompt, system=system_prompt,
                    max_tokens=12000, temperature=0.3, thinking=False,
                    node_name="ai_generate_map",
                )
                raw_content = content or ""
                # 全角标点转半角（LLM 中文 JSON 常见错误：： ， “ ”）
                sanitized = (raw_content.replace("：", ":").replace("，", ",")
                             .replace("“", '"').replace("”", '"')
                             .replace("‘", "'").replace("’", "'"))
                parsed = parse_json_safe(sanitized) if sanitized else None
                if not isinstance(parsed, dict):
                    parsed = _extract_json_anywhere(sanitized)
                # 统一成地点条目列表：JSON（new_locations/locations/keep+new）→ 文本行兜底
                loc_entries: list = []
                rel_entries: list = []
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("new_locations"), list):
                        loc_entries = parsed["new_locations"]
                    elif isinstance(parsed.get("locations"), list):
                        loc_entries = parsed["locations"]
                    else:
                        loc_entries = (parsed.get("keep") or []) + (parsed.get("new") or [])
                    rel_entries = parsed.get("relationships") or []
                if not rel_entries:
                    # 文本行关系兜底：关系|源|目标|类型|距离
                    rel_entries = _parse_relation_lines(raw_content)
                if not loc_entries:
                    # 纯文本行格式：每行一个地点 名称|类型|重要性|上级|描述
                    loc_entries = _parse_location_lines(raw_content)
                if not loc_entries:
                    logger.warning("AI 生成地图原始输出(前3000字): %s", raw_content[:3000])
                    raise ValueError(
                        "AI 未返回有效的世界地图方案"
                        + (f"（返回前 300 字：{raw_content[:300]}）" if raw_content else "")
                    )

                # ---- 3. 写库（智能合并） ----
                await emit({"type": "gen_stage", "stage": "写入地点与关系..."})
                created = updated = relations = 0
                all_names = {l.name for l in locations}

                # 写库阶段 1：补全已有地点（只补空字段，不覆盖已有内容）
                for raw_item in loc_entries:
                    item = _norm_loc_item(raw_item)
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    loc = next((l for l in locations if l.name == name), None)
                    if not loc:
                        continue
                    changed = False
                    for field in ("type", "tier", "layer", "importance", "parent_name", "ruler"):
                        val = str(item.get(field) or "").strip()
                        if val and not getattr(loc, field):
                            setattr(loc, field, val)
                            changed = True
                    plot_role = str(item.get("plot_role") or "").strip()
                    if plot_role and not (loc.plot_role or "").strip():
                        loc.plot_role = plot_role
                        changed = True
                    desc = str(item.get("description") or "").strip()
                    if desc and not (loc.description or "").strip():
                        loc.description = desc
                        changed = True
                    if changed:
                        updated += 1
                db.flush()

                # 写库阶段 2：新增地点（没匹配到已有地点的都尝试创建，上限 max_new）
                from novel_agent.bible.world_structure import classify_layer, classify_tier

                for raw_item in loc_entries:
                    if created >= max_new:
                        break
                    item = _norm_loc_item(raw_item)
                    name = str(item.get("name") or "").strip()
                    if not name or name in all_names:
                        continue
                    desc = str(item.get("description") or "").strip()
                    tier_val = str(item.get("tier") or "").strip()
                    layer_val = str(item.get("layer") or "").strip()
                    if not tier_val:
                        tier_val = classify_tier(name)
                    if not layer_val or layer_val == "surface":
                        layer_val = classify_layer(name, desc)
                    db.add(Location(
                        project_id=project_id, name=name,
                        type=str(item.get("type") or "city").strip() or "city",
                        tier=tier_val,
                        layer=layer_val or "surface",
                        importance=str(item.get("importance") or "").strip(),
                        parent_name=str(item.get("parent_name") or "").strip(),
                        ruler=str(item.get("ruler") or "").strip(),
                        plot_role=str(item.get("plot_role") or "").strip(),
                        description=desc,
                    ))
                    all_names.add(name)
                    created += 1
                db.flush()

                existing_rel = {(r.source_location, r.target_location, r.relation_type or "road") for r in rels}
                for raw_item in rel_entries:
                    item = _norm_loc_item(raw_item)
                    src = str(item.get("source") or "").strip()
                    tgt = str(item.get("target") or "").strip()
                    rtype = str(item.get("relation_type") or item.get("relationtype") or "road").strip() or "road"
                    if not src or not tgt or src == tgt:
                        continue
                    if src not in all_names or tgt not in all_names:
                        continue
                    if (src, tgt, rtype) in existing_rel:
                        continue
                    db.add(LocationRelationship(
                        project_id=project_id, source_location=src, target_location=tgt,
                        relation_type=rtype, distance=str(item.get("distance") or "").strip(),
                    ))
                    existing_rel.add((src, tgt, rtype))
                    relations += 1
                db.commit()

                # 兜底①：AI 未填上级时，用名称前缀推断父子关系并补写（如"灰烬农场带边缘哨站"→父"灰烬农场带"）
                all_locs = db.query(Location).filter(Location.project_id == project_id).all()
                parent_map = _infer_parent_names({loc.name for loc in all_locs})
                for loc in all_locs:
                    if not (loc.parent_name or "").strip() and loc.name in parent_map:
                        loc.parent_name = parent_map[loc.name]
                        updated += 1
                db.flush()

                # 兜底②：上级地点自动建 contains 关系（AI 漏输出关系时仍有点有线）
                for loc in all_locs:
                    parent = (loc.parent_name or "").strip()
                    if not parent or parent == loc.name:
                        continue
                    if parent not in all_names or loc.name not in all_names:
                        continue
                    if (parent, loc.name, "contains") in existing_rel:
                        continue
                    db.add(LocationRelationship(
                        project_id=project_id, source_location=parent, target_location=loc.name,
                        relation_type="contains", distance="",
                    ))
                    existing_rel.add((parent, loc.name, "contains"))
                    relations += 1

                # 兜底③：仍没有任何关系的地点自动连 road 链，保证地图连线丰富
                linked_names: set[str] = set()
                for src, tgt, _rt in existing_rel:
                    linked_names.add(src)
                    linked_names.add(tgt)
                isolated = [loc.name for loc in all_locs if loc.name not in linked_names]
                if isolated:
                    anchor = next((n for n in linked_names), None)
                    prev = anchor or isolated[0]
                    for nm in isolated:
                        if prev != nm and (prev, nm, "road") not in existing_rel:
                            db.add(LocationRelationship(
                                project_id=project_id, source_location=prev, target_location=nm,
                                relation_type="road", distance="",
                            ))
                            existing_rel.add((prev, nm, "road"))
                            relations += 1
                        prev = nm
                db.commit()

                await emit({"type": "gen_done", "created": created, "updated": updated,
                            "relations": relations, "total": len(all_names)})
            except Exception as e:
                logger.exception("AI 生成世界地图失败 (project_id=%d)", project_id)
                await emit({"type": "error", "error": str(e)})
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass
                await queue.put(None)  # 结束哨兵（正常/异常路径都保证 SSE 流结束）

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                etype = event.get("type", "message")
                yield {"event": etype, "data": json.dumps(event, ensure_ascii=False)}
        finally:
            if not task.done():
                task.cancel()

    return EventSourceResponse(event_gen(), ping=15)


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
