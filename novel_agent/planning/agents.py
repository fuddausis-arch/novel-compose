"""规划 agent：Planner（卷规划）/Architect（设定）。

每个 agent 调 LLM 产出结构化 JSON，经 DeltaApplier 写入圣经。
（Outliner 章节细纲 agent 已移除：章节细纲走 routes_generation 的弧/章生成链路）
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

from novel_agent.bible.models import Project
from novel_agent.llm.client import LLMClient


from novel_agent.utils.json_parser import parse_json_strict as _extract_json


PLANNER_SYSTEM = (
    "你是网文总编,专精长篇连载(100万字+)的卷次结构与爽点曲线设计。\n"
    "【评判标准】每卷有清晰核心冲突;爽点密度遵循'3-5章小爽/10-15章中爽/30-50章大高潮';"
    "卷末必有钩子引下一卷;全卷数服务于全书立意。\n"
    "【工作方式】先确定全书立意(核心爽点+主角长期目标),再拆卷,每卷标注核心冲突与升级节点。\n"
    "【禁忌】不写无冲突的过渡卷;不堆砌孤立地图;爽点不得偏离立意。只输出 JSON。"
)
ARCHITECT_SYSTEM = "你是网文设定师。设计世界观、角色、力量体系。只输出 JSON。"


class Planner:
    """总编：全书→卷→弧三级规划。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def plan(self, project: Project, target_chapters: int = 30,
                   custom_prompt: str = "",
                   target_volumes: int = 0,
                   golden_finger: str = "",
                   protagonist: str = "",
                   constitution: str = "") -> dict:
        # constitution/golden_finger/protagonist fallback：函数参数为空时从 DB 读取
        constitution = constitution or getattr(project, 'constitution', '') or ''
        golden_finger = golden_finger or getattr(project, 'golden_finger', '') or ''
        protagonist = protagonist or getattr(project, 'protagonist', '') or ''

        # 立意贯通：如果项目已有central_concept则注入，否则要求Planner产出
        existing_concept = ""
        if hasattr(project, 'central_concept') and project.central_concept:
            existing_concept = f"\n【已有全书立意（必须遵循）】\n{project.central_concept}\n"

        # 用户的全书规划要求（金手指/世界观/角色性格/卷次要求等）
        user_requirements = ""
        if custom_prompt and custom_prompt.strip():
            user_requirements = (
                f"\n【用户对全书的核心规划要求（必须遵循，不得偏离）】\n"
                f"{custom_prompt.strip()}\n"
            )

        # 金手指设定
        gf_block = ""
        if golden_finger and golden_finger.strip():
            gf_block = (
                f"\n【金手指设定（必须作为全书核心爽点引擎，卷次结构要围绕金手指的成长与升级展开）】\n"
                f"{golden_finger.strip()}\n"
            )

        # 主角设定
        protagonist_block = ""
        if protagonist and protagonist.strip():
            protagonist_block = (
                f"\n【主角设定（全书卷次结构必须围绕该主角的成长弧线、目标与承重矛盾展开）】\n"
                f"{protagonist.strip()}\n"
            )

        # 设定纲领/硬约束
        const_block = ""
        if constitution and constitution.strip():
            const_block = (
                f"\n【设定纲领/硬约束（全书不得违反的铁律）】\n"
                f"{constitution.strip()}\n"
            )

        # 本卷/全书章节数约束（C8：只约束第一卷，其余卷章数按剧情需要自定）
        chapter_directive = ""
        if target_chapters and target_chapters > 0:
            chapter_directive = (
                f"【第一卷强制章数】全书第一卷必须恰好 {target_chapters} 章，"
                f"不得多于或少于该数字。请在 {target_chapters} 章内完成第一卷的起承转合、"
                f"爽点曲线与卷末钩子。其余各卷的章数由你按剧情需要自行决定，"
                f"不必等于 {target_chapters}。\n\n"
            )

        # 卷数指令
        if target_volumes and target_volumes > 0:
            volume_directive = (
                f"为以下小说规划卷次结构，全书共 {target_volumes} 卷。"
                f"{'每卷章数由你根据该卷的核心冲突、升级节点与爽点密度自行决定（通常20-50章/卷），' if not chapter_directive else ''}"
                f"不必均分，要服务于全书立意。\n\n"
            )
        else:
            volume_directive = (
                f"为以下小说规划卷次结构，卷数由你根据全书立意与故事体量自行决定（通常3-8卷），"
                f"{'每卷章数亦由你根据该卷的核心冲突与爽点密度决定（通常20-50章/卷）。' if not chapter_directive else ''}"
                f"\n\n"
            )

        chapter_constraint = (
            f"- 全书第一卷的 chapters 必须严格等于 {target_chapters}，其余卷章数按剧情需要自定\n"
            if target_chapters and target_chapters > 0
            else "- 每卷chapters在20-50之间\n"
        )

        prompt = (
            f"{chapter_directive}"
            f"{volume_directive}"
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"{existing_concept}"
            f"{user_requirements}"
            f"{gf_block}"
            f"{protagonist_block}"
            f"{const_block}\n"
            f"输出 JSON：{{"
            f"\"central_concept\":{{\"core_hook\":\"核心爽点类型\","
            f"\"protagonist_goal\":\"主角长期目标\",\"taboos\":[\"立意禁忌\"]}},"
            f"\"volumes\":[{{\"name\":\"\",\"theme\":\"\","
            f"\"chapters\":0,\"summary\":\"\","
            f"\"climax\":\"卷末高潮\",\"end_hook\":\"引下一卷的悬念\","
            f"\"strand_ratio\":{{\"quest\":0.7,\"fire\":0.2,\"constellation\":0.1}}}}]}}\n"
            f"【硬约束】\n"
            f"- central_concept必须非空，core_hook是全书核心爽点类型\n"
            f"- strand_ratio三项之和必须≈1\n"
            f"{chapter_constraint}"
            f"- 卷与卷之间因果相连\n"
            f"- 如有用户规划要求/金手指/纲领，必须体现在 central_concept 与 volumes 设计中\n"
            f"只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=PLANNER_SYSTEM)
        result = _extract_json(raw)
        if not result:
            # 重试1次
            raw = await self.llm_client.generate(prompt + "\n\n请确保输出有效JSON格式。", system=PLANNER_SYSTEM)
            result = _extract_json(raw)
        return result


class Architect:
    """设定组：世界观/角色/力量体系。

    基于项目已有资产做增量设计，避免凭空造出与现有世界观冲突/重复的设定。
    """
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def design(self, project: Project, volume_plan: dict,
                     existing: dict | None = None,
                     custom_prompt: str = "",
                     golden_finger: str = "",
                     protagonist: str = "",
                     constitution: str = "") -> dict:
        existing = existing or {}
        # constitution/golden_finger/protagonist fallback：函数参数为空时从 DB 读取
        constitution = constitution or getattr(project, 'constitution', '') or ''
        golden_finger = golden_finger or getattr(project, 'golden_finger', '') or ''
        protagonist = protagonist or getattr(project, 'protagonist', '') or ''
        existing_block = self._format_existing(existing)
        # 用户的全书规划要求（金手指/世界观/角色性格等），约束设定师的设计
        user_requirements = ""
        if custom_prompt and custom_prompt.strip():
            user_requirements = (
                f"\n【用户对全书的核心规划要求（设定必须遵循，不得偏离）】\n"
                f"{custom_prompt.strip()}\n"
            )
        # 金手指设定：作为世界观/力量体系的核心，必须在设定中体现其机制、限制、成长
        gf_block = ""
        if golden_finger and golden_finger.strip():
            gf_block = (
                f"\n【金手指设定（必须在力量体系/世界设定中体现其机制、限制、代价与成长路径，"
                f"并设计主角如何获得、如何升级）】\n"
                f"{golden_finger.strip()}\n"
            )
        # 主角设定：必须围绕主角设计配套角色与世界观
        protagonist_block = ""
        if protagonist and protagonist.strip():
            protagonist_block = (
                f"\n【主角设定（所有新增角色和世界设定必须服务该主角的成长弧线；"
                f"若主角已在列表中，不得再创建同名角色）】\n"
                f"{protagonist.strip()}\n"
            )
        # 设定纲领/硬约束
        const_block = ""
        if constitution and constitution.strip():
            const_block = (
                f"\n【设定纲领/硬约束（设定不得违反这些铁律）】\n"
                f"{constitution.strip()}\n"
            )
        prompt = (
            f"为以下小说设计本卷新增的核心设定。\n\n"
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"卷规划：{json.dumps(volume_plan, ensure_ascii=False)}\n\n"
            f"{existing_block}"
            f"{user_requirements}"
            f"{gf_block}"
            f"{protagonist_block}"
            f"{const_block}\n"
            f"【增量设计约束】\n"
            f"- 以下资产已存在，不得重复创建，不得与之冲突\n"
            f"- 只输出本卷需要「新增」的角色和世界设定\n"
            f"- 若已有资产已足够支撑本卷，对应数组输出空 []\n"
            f"- 新角色必须与已有角色互补，不得重复已有角色定位\n"
            f"- 新世界设定必须基于已有世界观做扩展，不得推翻已有设定\n\n"
            f"【角色设计铁律——活人味三件套】\n"
            f"禁止用形容词列表描述角色（如'冷静、聪明、善良'），这种描述对生成活人反应毫无帮助。\n"
            f"每个角色必须填写以下三个字段：\n"
            f"1. core_contradiction（承重矛盾）：用一个矛盾定义角色。格式'他是___的人，但同时___'。\n"
            f"   例：'他是一个加班到凌晨的社畜，但心里始终觉得自己应该是做大事的人'\n"
            f"   例：'他是个杀人不眨眼的杀手，但每次杀人后会给目标家属匿名汇一笔钱'\n"
            f"   一个矛盾能生成100种独特反应，一打形容词生成0种。\n"
            f"2. sensory_memories（感官瞬间）：3-4个第一人称关键记忆片段，带感官细节。\n"
            f"   格式：用分号分隔的3-4个短句，每个是一个具体瞬间。\n"
            f"   例：'柴油味至今让我饿——爸爸的船烧这个；12岁葬礼那天我记得自己烦神父把我们姓念错了；进城第一周我在超市哭了，因为鱼是塑料包的'\n"
            f"   这些瞬间提供了感官记忆和未完成的关系，模型可以调用它们生成有历史痕迹的反应。\n"
            f"3. absolute_taboos（绝对禁令）：2-3条这个角色绝对不会做的事。\n"
            f"   例：'绝不会在别人面前哭；绝不会先说对不起；绝不会拒绝食物——小时候饿怕了'\n"
            f"   硬约束比软引导有效。\n"
            f"personality字段填一句总结即可（不要形容词列表），motivation填核心驱动力。\n\n"
            f"【世界设定铁律——日常细节强制】\n"
            f"世界设定不能只是'规则说明书'。每个世界设定必须包含：\n"
            f"- 硬规则：不可违反的世界法则（如'异能使用消耗生命源质'）\n"
            f"- 日常细节：普通人怎么吃饭/出行/通信/娱乐——3个具体的生活场景，让设定落地为可感知的生活\n"
            f"- 感官锚点：这个设定在视觉/听觉/嗅觉上是什么感觉？如'灰域酒吧的空气永远有铁锈味'\n"
            f"在content字段中同时写出硬规则、日常细节和感官锚点。\n\n"
            f"【地图纪律铁律】\n"
            f"- 设定地点时，标注'主角是否经过'\n"
            f"- 主角经过的地点：必须详写势力分布+等级划分+情节关联\n"
            f"- 主角不经过的地点：必须说明如何接入主线（配角出身/势力介入/伏笔载体），否则删除\n"
            f"- 禁止出现'垃圾地图'——介绍一次后再不出现的地点\n\n"
            f"【力量体系铁律】\n"
            f"- 每个境界/等级必须写清：能力范围、与上一级的差距、突破代价\n"
            f"- 等级差距要量化或具象（如'练气可碎石，筑基可断河，差距是10倍力量+御器'）\n"
            f"- 禁止模糊表述（'很强''远超'），必须给可比较的锚点\n\n"
            f"输出 JSON：{{\"characters\":[{{\"name\":\"\",\"role\":\","
            f"\"personality\":\"\",\"motivation\":\"\","
            f"\"core_contradiction\":\"\",\"sensory_memories\":\"\",\"absolute_taboos\":\"\"}}],"
            f"\"world_settings\":[{{\"category\":\"\",\"title\":\"\",\"content\":\"\"}}]}}\n"
            f"只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=ARCHITECT_SYSTEM)
        result = _extract_json(raw)
        if not result:
            # 重试1次
            raw = await self.llm_client.generate(prompt + "\n\n请确保输出有效JSON格式。", system=ARCHITECT_SYSTEM)
            result = _extract_json(raw)
        return result

    @staticmethod
    def _format_existing(existing: dict) -> str:
        """把已有资产格式化为 prompt 片段。"""
        if not existing:
            return ""
        parts = ["【项目已有资产（不得重复/冲突）】"]
        chars = existing.get("characters", [])
        if chars:
            names = "、".join(c for c in chars)
            parts.append(f"已有角色：{names}")
        ws = existing.get("world_settings", [])
        if ws:
            titles = "、".join(ws)
            parts.append(f"已有世界设定：{titles}")
        factions = existing.get("factions", [])
        if factions:
            parts.append(f"已有势力：{'、'.join(factions)}")
        monsters = existing.get("monsters", [])
        if monsters:
            parts.append(f"已有怪物/神明：{'、'.join(monsters)}")
        foreshadows = existing.get("foreshadows", [])
        if foreshadows:
            parts.append(f"已有伏笔ID：{'、'.join(foreshadows)}")
        if len(parts) == 1:
            return ""
        parts.append("")
        return "\n".join(parts) + "\n"
