# 网络小说设定体系 Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-TOOL: Use TodoWrite to track task progress. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 AI 小说生成器中实现势力组织关系系统、人物关系系统、怪物图鉴系统三大核心设定模块。

**架构：** 沿用现有 BibleRepository + FastAPI + React 前端三层架构，新增 SQLAlchemy 模型与 CRUD API，前端复用卡片/列表/编辑器模式，导入与一致性看板同步扩展。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, SQLite, React + TypeScript, Tailwind CSS, shadcn/ui

---

## 文件结构

### 后端新增/修改
- `novel_agent/bible/models.py` — 新增 `Faction`, `FactionRelationship`, `CharacterRelationship`, `Monster`
- `novel_agent/bible/repository.py` — 新增上述模型的 CRUD 方法
- `novel_agent/api/routes_bible.py` — 新增 API 路由与 Pydantic Input 模型
- `novel_agent/templates/prompts/import_parse.txt` — 扩展导入提示词

### 前端新增/修改
- `frontend/src/types.ts` — 新增 TypeScript 类型
- `frontend/src/api.ts` — 新增 API 方法
- `frontend/src/store.ts` — 新增状态与 refresh 方法
- `frontend/src/components/app-sidebar.tsx` — 新增导航分组
- `frontend/src/views/FactionsView.tsx` — 势力列表视图
- `frontend/src/views/FactionEditorView.tsx` — 势力编辑器
- `frontend/src/views/RelationshipsView.tsx` — 人物关系视图
- `frontend/src/views/RelationshipEditorView.tsx` — 关系编辑器
- `frontend/src/views/MonstersView.tsx` — 怪物图鉴视图
- `frontend/src/views/MonsterEditorView.tsx` — 怪物编辑器
- `frontend/src/components/workspace.tsx` — 注册新 Tab
- `frontend/src/App.tsx` — 处理新 AssetType 路由

### 测试
- `tests/test_repository.py` — 新增 Repository 单元测试
- `tests/test_api.py` — 新增 API 测试

---

## Task 1: 后端模型定义

**Files:**
- Modify: `novel_agent/bible/models.py`

- [ ] **Step 1: 新增 Faction 模型**

在 `Character` 类后追加：

```python
class Faction(Base):
    __tablename__ = "factions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    alias = Column(String, default="")
    type = Column(String, default="")
    alignment = Column(String, default="")
    description = Column(Text, default="")
    history = Column(Text, default="")
    goals = Column(Text, default="")
    hierarchy = Column(Text, default="")
    territories = Column(Text, default="")
    resources = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_faction_name"),)
```

- [ ] **Step 2: 新增 FactionRelationship 模型**

```python
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
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())
```

- [ ] **Step 3: 新增 CharacterRelationship 模型**

```python
class CharacterRelationship(Base):
    __tablename__ = "character_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_character = Column(String, nullable=False)
    target_character = Column(String, nullable=False)
    relation_type = Column(String, default="other")
    relation_subtype = Column(String, default="")
    strength = Column(Integer, default=0)
    description = Column(Text, default="")
    since_chapter = Column(Integer, default=0)
    status = Column(String, default="active")
    is_bidirectional = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "source_character", "target_character", "relation_type", name="uix_project_char_rel"),)
```

- [ ] **Step 4: 新增 Monster 模型**

```python
class Monster(Base):
    __tablename__ = "monsters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    alias = Column(String, default="")
    species = Column(String, default="")
    rank = Column(String, default="")
    attributes = Column(Text, default="")
    skills = Column(Text, default="")
    drops = Column(Text, default="")
    habitats = Column(Text, default="")
    behavior = Column(Text, default="")
    weaknesses = Column(Text, default="")
    lore = Column(Text, default="")
    first_appearance = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_monster_name"),)
```

- [ ] **Step 5: 确认导入**  
确保 `models.py` 已导入 `Boolean`, `UniqueConstraint`。

---

## Task 2: Repository 方法

**Files:**
- Modify: `novel_agent/bible/repository.py`

- [ ] **Step 1: Faction CRUD**

在 `BibleRepository` 中追加：

```python
    # Factions
    def list_factions(self):
        return self.db.query(Faction).filter(Faction.project_id == self.project_id).all()

    def get_faction(self, faction_id: int):
        return self.db.query(Faction).filter(Faction.project_id == self.project_id, Faction.id == faction_id).first()

    def get_faction_by_name(self, name: str):
        return self.db.query(Faction).filter(Faction.project_id == self.project_id, Faction.name == name).first()

    def create_faction(self, **kwargs):
        item = Faction(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_faction(self, faction_id: int) -> bool:
        item = self.get_faction(faction_id)
        if not item:
            return False
        self.db.query(FactionRelationship).filter(
            (FactionRelationship.source_faction_id == faction_id) | (FactionRelationship.target_faction_id == faction_id)
        ).delete(synchronize_session=False)
        self.db.delete(item)
        self.db.commit()
        return True
```

- [ ] **Step 2: FactionRelationship CRUD**

```python
    def list_faction_relationships(self):
        return self.db.query(FactionRelationship).filter(FactionRelationship.project_id == self.project_id).all()

    def get_faction_relationship(self, rel_id: int):
        return self.db.query(FactionRelationship).filter(FactionRelationship.project_id == self.project_id, FactionRelationship.id == rel_id).first()

    def create_faction_relationship(self, **kwargs):
        item = FactionRelationship(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_faction_relationship(self, rel_id: int) -> bool:
        item = self.get_faction_relationship(rel_id)
        if not item:
            return False
        self.db.delete(item)
        self.db.commit()
        return True
```

- [ ] **Step 3: CharacterRelationship CRUD**

```python
    def list_character_relationships(self):
        return self.db.query(CharacterRelationship).filter(CharacterRelationship.project_id == self.project_id).all()

    def get_character_relationship(self, rel_id: int):
        return self.db.query(CharacterRelationship).filter(CharacterRelationship.project_id == self.project_id, CharacterRelationship.id == rel_id).first()

    def create_character_relationship(self, **kwargs):
        item = CharacterRelationship(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_character_relationship(self, rel_id: int) -> bool:
        item = self.get_character_relationship(rel_id)
        if not item:
            return False
        self.db.delete(item)
        self.db.commit()
        return True
```

- [ ] **Step 4: Monster CRUD**

```python
    def list_monsters(self):
        return self.db.query(Monster).filter(Monster.project_id == self.project_id).all()

    def get_monster(self, monster_id: int):
        return self.db.query(Monster).filter(Monster.project_id == self.project_id, Monster.id == monster_id).first()

    def get_monster_by_name(self, name: str):
        return self.db.query(Monster).filter(Monster.project_id == self.project_id, Monster.name == name).first()

    def create_monster(self, **kwargs):
        item = Monster(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_monster(self, monster_id: int) -> bool:
        item = self.get_monster(monster_id)
        if not item:
            return False
        self.db.delete(item)
        self.db.commit()
        return True
```

- [ ] **Step 5: 运行 Repository 相关测试**

Run: `.venv\Scripts\activate && python -m pytest tests/test_repository.py -q`
Expected: 现有测试全部通过（新增模型尚未测试）

---

## Task 3: API 路由与 Pydantic 模型

**Files:**
- Modify: `novel_agent/api/routes_bible.py`

- [ ] **Step 1: 新增 Input 模型**

在 `WorldSettingInput` 附近追加：

```python
class FactionInput(BaseModel):
    name: str
    alias: str = ""
    type: str = ""
    alignment: str = ""
    description: str = ""
    history: str = ""
    goals: str = ""
    hierarchy: str = ""
    territories: str = ""
    resources: str = ""


class FactionRelationshipInput(BaseModel):
    source_faction_id: int
    target_faction_id: int
    relation_type: str = "neutral"
    strength: int = 0
    description: str = ""
    since_chapter: int = 0
    status: str = "active"


class CharacterRelationshipInput(BaseModel):
    source_character: str
    target_character: str
    relation_type: str = "other"
    relation_subtype: str = ""
    strength: int = 0
    description: str = ""
    since_chapter: int = 0
    status: str = "active"
    is_bidirectional: bool = True


class MonsterInput(BaseModel):
    name: str
    alias: str = ""
    species: str = ""
    rank: str = ""
    attributes: str = ""
    skills: str = ""
    drops: str = ""
    habitats: str = ""
    behavior: str = ""
    weaknesses: str = ""
    lore: str = ""
    first_appearance: int = 0
```

- [ ] **Step 2: 新增 Faction API 路由**

在 `import_settings` 函数前追加（或文件末尾）：

```python
# ---- 势力 ----
@router.get("/{project_id}/factions")
def list_factions(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                 "alignment": f.alignment, "description": f.description, "history": f.history,
                 "goals": f.goals, "hierarchy": f.hierarchy, "territories": f.territories,
                 "resources": f.resources} for f in repo.list_factions()]
    finally:
        db.close()


@router.post("/{project_id}/factions")
def create_faction(project_id: int, data: FactionInput):
    db, repo = _repo(project_id)
    try:
        if repo.get_faction_by_name(data.name):
            raise HTTPException(409, "势力名称已存在")
        f = repo.create_faction(**data.model_dump())
        return {"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                "alignment": f.alignment, "description": f.description, "history": f.history,
                "goals": f.goals, "hierarchy": f.hierarchy, "territories": f.territories,
                "resources": f.resources}
    finally:
        db.close()


@router.put("/{project_id}/factions/{faction_id}")
def update_faction(project_id: int, faction_id: int, data: FactionInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import Faction
        f = db.query(Faction).filter(Faction.project_id == project_id, Faction.id == faction_id).first()
        if not f:
            raise HTTPException(404, "势力不存在")
        for k, v in data.model_dump().items():
            setattr(f, k, v)
        db.commit(); db.refresh(f)
        return {"id": f.id, "name": f.name, "alias": f.alias, "type": f.type,
                "alignment": f.alignment, "description": f.description, "history": f.history,
                "goals": f.goals, "hierarchy": f.hierarchy, "territories": f.territories,
                "resources": f.resources}
    finally:
        db.close()


@router.delete("/{project_id}/factions/{faction_id}")
def delete_faction(project_id: int, faction_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_faction(faction_id):
            raise HTTPException(404, "势力不存在")
        return {"deleted": True}
    finally:
        db.close()
```

- [ ] **Step 3: 新增 FactionRelationship API 路由**

```python
# ---- 势力关系 ----
@router.get("/{project_id}/faction-relationships")
def list_faction_relationships(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": r.id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
                 "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
                 "since_chapter": r.since_chapter, "status": r.status} for r in repo.list_faction_relationships()]
    finally:
        db.close()


@router.post("/{project_id}/faction-relationships")
def create_faction_relationship(project_id: int, data: FactionRelationshipInput):
    db, repo = _repo(project_id)
    try:
        r = repo.create_faction_relationship(**data.model_dump())
        return {"id": r.id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
                "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
                "since_chapter": r.since_chapter, "status": r.status}
    finally:
        db.close()


@router.put("/{project_id}/faction-relationships/{rel_id}")
def update_faction_relationship(project_id: int, rel_id: int, data: FactionRelationshipInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import FactionRelationship
        r = db.query(FactionRelationship).filter(FactionRelationship.project_id == project_id, FactionRelationship.id == rel_id).first()
        if not r:
            raise HTTPException(404, "关系不存在")
        for k, v in data.model_dump().items():
            setattr(r, k, v)
        db.commit(); db.refresh(r)
        return {"id": r.id, "source_faction_id": r.source_faction_id, "target_faction_id": r.target_faction_id,
                "relation_type": r.relation_type, "strength": r.strength, "description": r.description,
                "since_chapter": r.since_chapter, "status": r.status}
    finally:
        db.close()


@router.delete("/{project_id}/faction-relationships/{rel_id}")
def delete_faction_relationship(project_id: int, rel_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_faction_relationship(rel_id):
            raise HTTPException(404, "关系不存在")
        return {"deleted": True}
    finally:
        db.close()
```

- [ ] **Step 4: 新增 CharacterRelationship API 路由**

```python
# ---- 人物关系 ----
@router.get("/{project_id}/character-relationships")
def list_character_relationships(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                 "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                 "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                 "is_bidirectional": r.is_bidirectional} for r in repo.list_character_relationships()]
    finally:
        db.close()


@router.post("/{project_id}/character-relationships")
def create_character_relationship(project_id: int, data: CharacterRelationshipInput):
    db, repo = _repo(project_id)
    try:
        r = repo.create_character_relationship(**data.model_dump())
        return {"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                "is_bidirectional": r.is_bidirectional}
    finally:
        db.close()


@router.put("/{project_id}/character-relationships/{rel_id}")
def update_character_relationship(project_id: int, rel_id: int, data: CharacterRelationshipInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import CharacterRelationship
        r = db.query(CharacterRelationship).filter(CharacterRelationship.project_id == project_id, CharacterRelationship.id == rel_id).first()
        if not r:
            raise HTTPException(404, "关系不存在")
        for k, v in data.model_dump().items():
            setattr(r, k, v)
        db.commit(); db.refresh(r)
        return {"id": r.id, "source_character": r.source_character, "target_character": r.target_character,
                "relation_type": r.relation_type, "relation_subtype": r.relation_subtype, "strength": r.strength,
                "description": r.description, "since_chapter": r.since_chapter, "status": r.status,
                "is_bidirectional": r.is_bidirectional}
    finally:
        db.close()


@router.delete("/{project_id}/character-relationships/{rel_id}")
def delete_character_relationship(project_id: int, rel_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_character_relationship(rel_id):
            raise HTTPException(404, "关系不存在")
        return {"deleted": True}
    finally:
        db.close()
```

- [ ] **Step 5: 新增 Monster API 路由**

```python
# ---- 怪物 ----
@router.get("/{project_id}/monsters")
def list_monsters(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"id": m.id, "name": m.name, "alias": m.alias, "species": m.species, "rank": m.rank,
                 "attributes": m.attributes, "skills": m.skills, "drops": m.drops, "habitats": m.habitats,
                 "behavior": m.behavior, "weaknesses": m.weaknesses, "lore": m.lore,
                 "first_appearance": m.first_appearance} for m in repo.list_monsters()]
    finally:
        db.close()


@router.post("/{project_id}/monsters")
def create_monster(project_id: int, data: MonsterInput):
    db, repo = _repo(project_id)
    try:
        if repo.get_monster_by_name(data.name):
            raise HTTPException(409, "怪物名称已存在")
        m = repo.create_monster(**data.model_dump())
        return {"id": m.id, "name": m.name, "alias": m.alias, "species": m.species, "rank": m.rank,
                "attributes": m.attributes, "skills": m.skills, "drops": m.drops, "habitats": m.habitats,
                "behavior": m.behavior, "weaknesses": m.weaknesses, "lore": m.lore,
                "first_appearance": m.first_appearance}
    finally:
        db.close()


@router.put("/{project_id}/monsters/{monster_id}")
def update_monster(project_id: int, monster_id: int, data: MonsterInput):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import Monster
        m = db.query(Monster).filter(Monster.project_id == project_id, Monster.id == monster_id).first()
        if not m:
            raise HTTPException(404, "怪物不存在")
        for k, v in data.model_dump().items():
            setattr(m, k, v)
        db.commit(); db.refresh(m)
        return {"id": m.id, "name": m.name, "alias": m.alias, "species": m.species, "rank": m.rank,
                "attributes": m.attributes, "skills": m.skills, "drops": m.drops, "habitats": m.habitats,
                "behavior": m.behavior, "weaknesses": m.weaknesses, "lore": m.lore,
                "first_appearance": m.first_appearance}
    finally:
        db.close()


@router.delete("/{project_id}/monsters/{monster_id}")
def delete_monster(project_id: int, monster_id: int):
    db, repo = _repo(project_id)
    try:
        if not repo.delete_monster(monster_id):
            raise HTTPException(404, "怪物不存在")
        return {"deleted": True}
    finally:
        db.close()
```

- [ ] **Step 6: 扩展 ImportData**

修改 `ImportData`：

```python
class ImportData(BaseModel):
    """批量导入设定数据（世界观/势力/关系/角色/伏笔/大纲/怪物）。"""
    world_settings: list[WorldSettingInput] = []
    factions: list[FactionInput] = []
    faction_relationships: list[FactionRelationshipInput] = []
    character_relationships: list[CharacterRelationshipInput] = []
    characters: list[CharacterInput] = []
    foreshadows: list[ForeshadowInput] = []
    outlines: list[OutlineInput] = []
    monsters: list[MonsterInput] = []
```

修改 `_apply_import_data` 增加导入逻辑（跳过同名的 faction/monster，按唯一约束处理关系）。

- [ ] **Step 7: 扩展 _parse_text**

在返回 ImportData 时增加：

```python
    return ImportData(
        world_settings=[...],
        factions=[FactionInput(**x) for x in parsed.get("factions", [])],
        faction_relationships=[FactionRelationshipInput(**x) for x in parsed.get("faction_relationships", [])],
        character_relationships=[CharacterRelationshipInput(**x) for x in parsed.get("character_relationships", [])],
        characters=[...],
        foreshadows=[...],
        outlines=[...],
        monsters=[MonsterInput(**x) for x in parsed.get("monsters", [])],
    )
```

- [ ] **Step 8: 扩展导入提示词**

修改 `novel_agent/templates/prompts/import_parse.txt`，在 JSON 格式示例中增加 `factions`, `faction_relationships`, `character_relationships`, `monsters` 字段。

---

## Task 4: 后端测试

**Files:**
- Modify: `tests/test_repository.py`, `tests/test_api.py`

- [ ] **Step 1: 新增 Repository 测试**

为 Faction、FactionRelationship、CharacterRelationship、Monster 各写 create/list/delete 测试。

- [ ] **Step 2: 新增 API 测试**

为新增 API 路由写 TestClient 测试，覆盖创建、列表、更新、删除。

- [ ] **Step 3: 运行全部后端测试**

Run: `.venv\Scripts\activate && python -m pytest -q`
Expected: 全部通过

---

## Task 5: 前端类型与 API

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`

- [ ] **Step 1: 新增 TypeScript 类型**

在 `types.ts` 中追加：

```typescript
export interface Faction {
  id: number;
  project_id: number;
  name: string;
  alias: string;
  type: string;
  alignment: string;
  description: string;
  history: string;
  goals: string;
  hierarchy: string;
  territories: string;
  resources: string;
  created_at: string;
  updated_at: string;
}

export interface FactionRelationship {
  id: number;
  project_id: number;
  source_faction_id: number;
  target_faction_id: number;
  relation_type: string;
  strength: number;
  description: string;
  since_chapter: number;
  status: string;
}

export interface CharacterRelationship {
  id: number;
  project_id: number;
  source_character: string;
  target_character: string;
  relation_type: string;
  relation_subtype: string;
  strength: number;
  description: string;
  since_chapter: number;
  status: string;
  is_bidirectional: boolean;
}

export interface Monster {
  id: number;
  project_id: number;
  name: string;
  alias: string;
  species: string;
  rank: string;
  attributes: string;
  skills: string;
  drops: string;
  habitats: string;
  behavior: string;
  weaknesses: string;
  lore: string;
  first_appearance: number;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: 新增 API 方法**

在 `api.ts` 中追加：

```typescript
  // Factions
  listFactions: (projectId: number) => request<Faction[]>(`/api/bible/${projectId}/factions`),
  createFaction: (projectId: number, data: Partial<Faction>) => request<Faction>(`/api/bible/${projectId}/factions`, { method: "POST", body: JSON.stringify(data) }),
  updateFaction: (projectId: number, id: number, data: Partial<Faction>) => request<Faction>(`/api/bible/${projectId}/factions/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteFaction: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/factions/${id}`, { method: "DELETE" }),

  // Faction relationships
  listFactionRelationships: (projectId: number) => request<FactionRelationship[]>(`/api/bible/${projectId}/faction-relationships`),
  createFactionRelationship: (projectId: number, data: Partial<FactionRelationship>) => request<FactionRelationship>(`/api/bible/${projectId}/faction-relationships`, { method: "POST", body: JSON.stringify(data) }),
  updateFactionRelationship: (projectId: number, id: number, data: Partial<FactionRelationship>) => request<FactionRelationship>(`/api/bible/${projectId}/faction-relationships/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteFactionRelationship: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/faction-relationships/${id}`, { method: "DELETE" }),

  // Character relationships
  listCharacterRelationships: (projectId: number) => request<CharacterRelationship[]>(`/api/bible/${projectId}/character-relationships`),
  createCharacterRelationship: (projectId: number, data: Partial<CharacterRelationship>) => request<CharacterRelationship>(`/api/bible/${projectId}/character-relationships`, { method: "POST", body: JSON.stringify(data) }),
  updateCharacterRelationship: (projectId: number, id: number, data: Partial<CharacterRelationship>) => request<CharacterRelationship>(`/api/bible/${projectId}/character-relationships/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteCharacterRelationship: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/character-relationships/${id}`, { method: "DELETE" }),

  // Monsters
  listMonsters: (projectId: number) => request<Monster[]>(`/api/bible/${projectId}/monsters`),
  createMonster: (projectId: number, data: Partial<Monster>) => request<Monster>(`/api/bible/${projectId}/monsters`, { method: "POST", body: JSON.stringify(data) }),
  updateMonster: (projectId: number, id: number, data: Partial<Monster>) => request<Monster>(`/api/bible/${projectId}/monsters/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteMonster: (projectId: number, id: number) => request<void>(`/api/bible/${projectId}/monsters/${id}`, { method: "DELETE" }),
```

- [ ] **Step 3: 扩展导入 API 类型**

`parseDocument` / `parseFile` / `importStructured` 返回/参数类型增加 `factions`, `faction_relationships`, `character_relationships`, `monsters`。

---

## Task 6: 前端 Store 扩展

**Files:**
- Modify: `frontend/src/store.ts`

- [ ] **Step 1: 扩展 AppState**

新增状态字段：

```typescript
  factions: Faction[];
  factionRelationships: FactionRelationship[];
  characterRelationships: CharacterRelationship[];
  monsters: Monster[];
```

- [ ] **Step 2: 扩展 refreshAssets**

`refreshAssets` 在加载 characters/foreshadows/outlines/worldSettings 之外，同时加载 factions、factionRelationships、characterRelationships、monsters。

- [ ] **Step 3: 新增独立刷新方法**

```typescript
  refreshFactions: () => Promise<void>;
  refreshFactionRelationships: () => Promise<void>;
  refreshCharacterRelationships: () => Promise<void>;
  refreshMonsters: () => Promise<void>;
```

---

## Task 7: 前端视图与编辑器

**Files:**
- Create: `frontend/src/views/FactionsView.tsx`
- Create: `frontend/src/views/FactionEditorView.tsx`
- Create: `frontend/src/views/RelationshipsView.tsx`
- Create: `frontend/src/views/RelationshipEditorView.tsx`
- Create: `frontend/src/views/MonstersView.tsx`
- Create: `frontend/src/views/MonsterEditorView.tsx`

- [ ] **Step 1: FactionsView**

卡片网格展示势力，支持搜索、按 type/alignment 筛选、点击打开编辑器。

- [ ] **Step 2: FactionEditorView**

表单字段：name, alias, type, alignment, description, history, goals, hierarchy, territories, resources。底部子标签管理该势力与其他势力的关系（FactionRelationship 列表）。

- [ ] **Step 3: RelationshipsView**

人物关系列表，支持按角色名筛选，显示 source → target、关系类型、强度条、状态。

- [ ] **Step 4: RelationshipEditorView**

表单字段：source_character, target_character, relation_type, relation_subtype, strength, description, since_chapter, status, is_bidirectional。source/target 使用角色下拉选择。

- [ ] **Step 5: MonstersView**

图鉴卡片网格/列表，支持搜索、按 rank/species/habitats 筛选。

- [ ] **Step 6: MonsterEditorView**

表单字段：name, alias, species, rank, attributes, skills, drops, habitats, behavior, weaknesses, lore, first_appearance。attributes/skills/drops 使用 Textarea 编辑 JSON 字符串。

---

## Task 8: 侧边栏与路由

**Files:**
- Modify: `frontend/src/components/app-sidebar.tsx`
- Modify: `frontend/src/components/workspace.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: AppSidebar 新增导航分组**

新增分组：
- 世界：世界观设定、势力组织
- 人物：角色、关系网
- 生物/物品：怪物图鉴

- [ ] **Step 2: Workspace 注册新 Tab**

在 `workspace.tsx` 中增加：
- `activeTab === "factions" && <FactionsView ... />`
- `activeTab === "relationships" && <RelationshipsView ... />`
- `activeTab === "monsters" && <MonstersView ... />`
- asset editor 路由增加对 faction/relationship/monster 的处理

- [ ] **Step 3: App.tsx 更新 Tab 与 AssetType**

扩展 `Tab` 与 `AssetType` 类型，处理新建与选中逻辑。

---

## Task 9: 导入与一致性看板扩展

**Files:**
- Modify: `frontend/src/components/import-preview-dialog.tsx`
- Modify: `frontend/src/hooks/useImportActions.ts`
- Modify: `novel_agent/api/routes_bible.py` 一致性看板

- [ ] **Step 1: ImportPreviewDialog 增加新类型分区**

增加 Faction、FactionRelationship、CharacterRelationship、Monster 的预览分区。

- [ ] **Step 2: useImportActions 成功消息更新**

导入成功 toast 增加新势力/关系/怪物计数。

- [ ] **Step 3: 一致性看板扩展**

在 `get_consistency_dashboard` 中新增检测：
- 势力关系中 source/target 指向不存在的 faction
- 人物关系中 source/target 指向不存在的 character
- 怪物首次出场章节大于当前总章节数

---

## Task 10: 构建与测试验证

- [ ] **Step 1: 前端构建**

Run: `cd frontend && npm run build`
Expected: 成功，无 TypeScript 错误

- [ ] **Step 2: 后端测试**

Run: `.venv\Scripts\activate && python -m pytest -q`
Expected: 全部通过

- [ ] **Step 3: 重启后端并验证 API**

Run: `.venv\Scripts\activate && python -m novel_agent.cli serve --port 8000`
使用浏览器或 curl 验证新 API 可访问。

---

## Spec 覆盖检查

| Spec 要求 | 对应任务 |
|---|---|
| 势力组织关系系统 | Task 1/2/3/7/8 |
| 人物关系系统 | Task 1/2/3/7/8 |
| 怪物图鉴系统 | Task 1/2/3/7/8 |
| 动态更新（关系演变） | Task 9 一致性看板 + StateChange 后续扩展 |
| 与导入联动 | Task 3/9 |
| 与主线/支线任务联动 | Phase 2 通过 Quest 模块实现 |

---

## 执行方式

Plan complete and saved to `docs/superpowers/plans/2026-06-19-novel-setting-system-phase1.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using TodoWrite, batch execution with checkpoints.

Which approach?
