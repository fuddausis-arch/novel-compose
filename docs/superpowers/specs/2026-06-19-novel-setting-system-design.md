# 网络小说设定体系与动态要素设计规格书

## 1. 调研结论

参考 NovelForge、Arboris、AI_NovelGenerator、webnovel-author、Novel Writer、Plot Bunni、story-generator 等开源/商业项目后，可归纳出网络小说创作工具普遍包含的设定要素：

| 项目 | 核心设定能力 |
|---|---|
| NovelForge | 卡片式元素、Pydantic 动态输出模型、Neo4j 知识图谱（角色关系/立场变化）、@DSL 上下文注入 |
| Arboris | 世界观、 factions、locations、角色关系网、大纲、草稿版本管理 |
| AI_NovelGenerator | 世界观工坊、状态追踪、伏笔管理、向量检索、一致性审校 |
| webnovel-author | 角色、世界构建、伏笔、时间线、LitRPG 属性、 romance arcs |
| Novel Writer | 角色关系图谱、派系管理、情感发展追踪、地点/场景/文化管理 |
| Plot Bunni | Concept Cache（角色/地点/lore）、分层大纲、视觉网格 |
| story-generator | 关系网络、派系系统、地点管理、物品追踪、历史事件 |

**共性发现**：
1. 角色关系与派系关系是所有工具都重点支持的图结构数据。
2. 地点（Location）与势力（Faction）通常成对出现，并需要层级与交叉引用。
3. 怪物/敌人通常作为「生物图鉴」或「Bestiary」独立模块，尤其在玄幻、奇幻、游戏化题材中。
4. 动态一致性检查（关系冲突、状态变化、伏笔回收）是长篇小说刚需。

## 2. 网络小说设定要素全景

### 2.1 静态基础设定（创作初期确立）

| 要素 | 说明 | 对应本项目模型 |
|---|---|---|
| 世界观背景 | 世界背景、地理环境、社会结构、科技/魔法水平 | `WorldSetting` |
| 核心规则 | 力量体系、特殊规则、关键历史事件 | `WorldSetting` + `TimelineEvent` |
| 主要角色 | 背景、性格、能力、关系 | `Character` + `CharacterRelationship` |
| 故事主线 | 核心冲突、走向、阶段性目标 | `Outline` + `Foreshadow` |
| 叙事风格 | 人称、节奏、语言风格 | `Project.style` |
| 势力/组织 | 基本信息、层级、敌对/同盟、历史 | `Faction` + `FactionRelationship` |
| 地点/场景 | 区域、城市、建筑、环境特征 | `Location` |
| 物品/法宝 | 属性、效果、持有者、来历 | `Item` |
| 种族/血脉 | 生理特征、天赋、社会定位 | `Race` |
| 功法/技能 | 等级、效果、修炼条件 | `Skill` |
| 怪物图鉴 | 属性、技能、掉落、出没区域、背景 | `Monster` |

### 2.2 动态更新要素（创作过程中持续完善）

| 要素 | 说明 | 对应本项目机制 |
|---|---|---|
| 角色成长弧线 | 能力提升、性格转变、目标变化 | `StateChange` + `CharacterRelationship` 权重/状态演变 |
| 势力关系演变 | 结盟、敌对、利益关系变化 | `FactionRelationship` 动态类型与权重 |
| 世界观拓展 | 新区域、新规则、历史谜团揭露 | `Location`/`WorldSetting` 新增 + `TimelineEvent` |
| 情节线索发展 | 伏笔回收、新支线开启 | `Foreshadow` 状态更新 |
| 任务/事件联动 | 主线/支线任务与设定产生关联 | `Quest` + 与角色/地点/势力关联 |
| 读者反馈整合 | 节奏或设定补充 | 人工编辑 `WorldSetting`/`Character` 等 |

## 3. 第一阶段实现范围

为控制一次迭代规模，第一阶段聚焦用户明确提出的三大核心系统，同时预留扩展接口：

1. **势力组织关系系统（Faction）**
2. **人物关系系统（CharacterRelationship）**
3. **怪物图鉴系统（Monster）**

其余要素（Location、Item、Race、Skill、Quest）作为第二阶段扩展，但第一阶段的数据模型和 API 命名需避免与第二阶段冲突。

## 4. 数据模型设计

### 4.1 Faction（势力/组织）

```python
class Faction(Base):
    id: int
    project_id: int
    name: str              # 势力名称，唯一
    alias: str             # 别名/简称
    type: str              # 类型：宗门/帝国/商会/世家/邪道/其他
    alignment: str         # 立场：守序/中立/混乱/正义/邪恶/中立
    description: str       # 简介
    history: str           # 历史背景
    goals: str             # 目标/宗旨
    hierarchy: str         # 层级结构（JSON 或文本）
    territories: str       # 控制区域（文本，二期关联 Location）
    resources: str         # 资源/财富
    created_at: str
    updated_at: str
```

### 4.2 FactionRelationship（势力间关系）

```python
class FactionRelationship(Base):
    id: int
    project_id: int
    source_faction_id: int    # 源势力
    target_faction_id: int    # 目标势力
    relation_type: str        # alliance/rival/vassal/trade/neutral/hostile/unknown
    strength: int             # 关系强度 -10 ~ 10
    description: str          # 关系描述
    since_chapter: int        # 从哪一章开始
    status: str               # active/resolved/frozen
    created_at: str
    updated_at: str
```

### 4.3 CharacterRelationship（人物关系）

```python
class CharacterRelationship(Base):
    id: int
    project_id: int
    source_character: str     # 源角色名
    target_character: str     # 目标角色名
    relation_type: str        # family/master-disciple/friend/enemy/lover/rival/colleague/ally/other
    relation_subtype: str     # 细分：父亲/师傅/结拜兄弟/宿敌 等
    strength: int             # 亲密度 -10 ~ 10
    description: str          # 关系描述
    since_chapter: int        # 关系起始章节
    status: str               # active/estranged/broken/deceased
    is_bidirectional: bool    # 是否双向（父子是双向，师徒可单向）
    created_at: str
    updated_at: str
```

### 4.4 Monster（怪物图鉴）

```python
class Monster(Base):
    id: int
    project_id: int
    name: str              # 怪物名称
    alias: str             # 别名
    species: str           # 种族/纲目
    rank: str              # 等级/境界
    attributes: str        # 属性（JSON：HP/攻击/防御/速度/元素属性等）
    skills: str            # 技能列表（JSON）
    drops: str             # 掉落物品（JSON，二期关联 Item）
    habitats: str          # 出没区域（文本，二期关联 Location）
    behavior: str          # 行为习性
    weaknesses: str        # 弱点
    lore: str              # 背景故事
    first_appearance: int  # 首次出场章节
    created_at: str
    updated_at: str
```

## 5. API 设计

所有接口挂载在 `/api/bible/{project_id}/` 下，与现有 Character/Foreshadow/Outline 保持一致风格。

### 5.1 Faction

- `GET /factions` — 列表
- `POST /factions` — 创建
- `PUT /factions/{faction_id}` — 更新
- `DELETE /factions/{faction_id}` — 删除

### 5.2 FactionRelationship

- `GET /faction-relationships` — 列表
- `POST /faction-relationships` — 创建
- `PUT /faction-relationships/{id}` — 更新
- `DELETE /faction-relationships/{id}` — 删除

### 5.3 CharacterRelationship

- `GET /character-relationships` — 列表
- `POST /character-relationships` — 创建
- `PUT /character-relationships/{id}` — 更新
- `DELETE /character-relationships/{id}` — 删除

### 5.4 Monster

- `GET /monsters` — 列表
- `POST /monsters` — 创建
- `PUT /monsters/{monster_id}` — 更新
- `DELETE /monsters/{monster_id}` — 删除

### 5.5 导入扩展

文档导入（`parse-document`、`parse-file`、`import`）的 JSON 输出增加：

```json
{
  "factions": [...],
  "faction_relationships": [...],
  "character_relationships": [...],
  "monsters": [...]
}
```

## 6. 前端设计

### 6.1 侧边栏新增导航

在现有「角色/伏笔/大纲/章节」下方增加分组：

```
世界
  - 世界观设定（现有 WorldView）
  - 势力组织（新 FactionsView）
  - 地点（二期占位）
人物
  - 角色（现有 CharactersView）
  - 关系网（新 RelationshipsView）
生物/物品
  - 怪物图鉴（新 MonstersView）
  - 道具法宝（二期占位）
```

### 6.2 视图方案

| 视图 | 功能 |
|---|---|
| FactionsView | 卡片列表展示势力；支持搜索/筛选；点击打开编辑器 |
| FactionEditor | 表单编辑势力字段； Relations 子标签管理该势力与其他势力关系 |
| RelationshipsView | 角色关系网/列表；支持按角色筛选 |
| RelationshipEditor | 编辑关系类型、强度、描述、起始章节、状态 |
| MonstersView | 图鉴卡片网格/列表；支持按等级/出没区域筛选 |
| MonsterEditor | 编辑怪物所有字段；JSON 编辑器用于 attributes/skills/drops |

### 6.3 关系可视化（MVP 阶段）

第一阶段不引入完整图可视化库。关系以「列表 + 简单连线示意」呈现，每个关系项显示源→目标、关系类型、强度条。二期可引入 D3.js 或 Cytoscape.js 做真正的关系图谱。

## 7. 与现有系统的联动

1. **一致性看板**：新增「势力冲突检测」「角色关系矛盾检测」「怪物属性异常检测」。
2. **状态变更（StateChange）**：当角色关系或势力关系在章节中发生变化时，自动写入 `StateChange`。
3. **AI 生成**：世界生成、角色生成、大纲生成时可引用 Faction/Monster 数据作为上下文。
4. **导入**：文档解析自动识别势力、关系、怪物，进入预览后选择性导入。

## 8. 实现阶段

### 阶段 1：三大核心系统
1. 后端模型 + Repository 方法
2. API CRUD
3. 前端类型 + API 封装
4. 新增视图与编辑器
5. 侧边栏导航调整
6. 导入提示词扩展
7. 一致性检测扩展

### 阶段 2：扩展要素
1. Location、Item、Race、Skill、Quest 数据模型与 CRUD
2. 关系图谱可视化
3. 地图/时间线视图
4. LitRPG 属性面板

## 9. 创作建议

1. **先建骨架后填肉**：先创建势力、主要角色、核心规则，再补充怪物、物品细节。
2. **关系即剧情**：派系关系和人物关系的变化本身就是情节驱动力，应随章节推进持续更新。
3. **怪物服务于世界观**：怪物设计应反映力量体系和生态环境，避免为打怪而打怪。
4. **利用动态要素做钩子**：势力结盟破裂、角色关系恶化、新区域开放都是天然的高潮点。
