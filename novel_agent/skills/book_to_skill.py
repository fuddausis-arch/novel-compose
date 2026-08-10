"""Book-to-Skill：把一本书提炼成结构化技能。

流程：
  1. 提取全文（file_extract）
  2. 检测章节（book_parser）
  3. LLM 逐章提炼（总结核心 + 提取技法/原则 + 关键术语）
  4. 生成全局索引（术语表 + 速查表）
  5. 组装成 skill JSON（兼容 routes_skills 的存储格式）

设计原则（参考 book-to-skill 开源项目）：
  - 只存储提炼后的摘要，不存储原文（版权安全）
  - 核心索引 ~4K token，章节按需加载
  - 生成时按关键词匹配只注入相关章节
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from novel_agent.skills.book_parser import Chapter, detect_chapters

logger = logging.getLogger(__name__)

# 每章提炼 prompt：融入蒸馏思想（features + guidelines + tags）
# 与 distillation/engine.py 的 ROUND_DIMENSIONS 对齐，但聚焦"技法"而非"风格"
_CHAPTER_SUMMARY_PROMPT = """你是一位写作技法拆书专家。请仔细阅读以下书籍章节内容，提炼出对小说写作者有用的结构化知识。

## 章节标题
{title}

## 章节内容
{content}

## 输出要求
只输出一个 JSON 对象（不要输出任何其他文字、不要用 markdown 围栏），格式：
{{
  "name": "本章技法名称（≤12字）",
  "description": "一句话概括本章核心技法",
  "features": ["具体技法特征，每条附带原文例证", "..."],
  "guidelines": ["可执行的写作规则，供后续生成时直接遵守", "..."],
  "tags": ["关键词标签", "..."],
  "glossary": ["关键术语：简要解释", "..."]
}}

其中 features 5-10 条，guidelines 5-10 条，tags 2-5 个，glossary 0-5 条。
注意：只提炼知识，不要照抄原文段落。features 要具体可感，guidelines 要可操作。"""


_OVERVIEW_PROMPT = """你是一位写作技法拆书专家。以下是一本书各章节的提炼摘要。请基于这些摘要，生成一份全局概览。

## 各章摘要
{summaries}

## 输出要求
请用中文输出以下结构（markdown 格式）：

### 全书主旨
（1-2 句话概括这本书的核心方法论）

### 章节索引
（列出所有章节，格式：`- 第N章 章节标题 - 关键词1、关键词2、关键词3`）

### 核心术语表
（汇总全书关键术语，按字母/笔画排序，格式：`- **术语**：解释（见第N章）`）

### 速查表
（最常用的写作决策规则，格式：`| 场景 | 原则 | 来源 |`）

注意：输出要精炼，这是供 AI 按需查询的索引，不是读书笔记。"""


@dataclass
class SkillSection:
    """技能的一个章节段落。"""
    name: str
    content: str
    keywords: list[str] = field(default_factory=list)
    source_chapter: int = 0  # 源章节序号（0-based）


@dataclass
class BookSkill:
    """拆书生成的完整技能包。"""
    name: str                    # 技能名（slug）
    description: str             # 一句话描述
    overview: str                # 全局概览（SKILL.md 核心）
    sections: list[SkillSection] # 按章拆分的知识段落
    glossary: str                # 术语表
    cheatsheet: str              # 速查表

    def to_skill_json(self) -> dict:
        """转换为 routes_skills 兼容的 JSON 格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "enabled": True,
            "auto_inject": True,
            "sections": [
                {
                    "name": s.name,
                    "content": s.content,
                    "keywords": s.keywords,
                    "source_chapter": s.source_chapter,
                }
                for s in self.sections
            ],
            # overview / glossary / cheatsheet 拼入第一个 section 作为索引
            "overview": self.overview,
            "glossary": self.glossary,
            "cheatsheet": self.cheatsheet,
        }


def _slugify(title: str) -> str:
    """把书名转成 slug（技能名）。"""
    import re
    # 保留中文、字母、数字、连字符
    slug = re.sub(r"[^\w\u4e00-\u9fff\-]", "-", title.strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:50] if slug else "book-skill"


def _extract_keywords(summary: str) -> list[str]:
    """从摘要中提取关键词（简单实现：取粗体词 + 高频名词）。"""
    import re
    # 提取 **加粗** 的词
    bold = re.findall(r"\*\*(.+?)\*\*", summary)
    # 过滤过短或过长的
    keywords = [k.strip() for k in bold if 2 <= len(k.strip()) <= 20]
    # 去重，保留顺序
    seen: set[str] = set()
    result: list[str] = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result[:10]  # 每章最多 10 个关键词


async def summarize_chapter(
    client,
    chapter: Chapter,
    max_input_chars: int = 8000,
) -> SkillSection:
    """用 LLM 提炼一个章节（融入蒸馏的 features/guidelines/tags 格式）。

    Args:
        client: LLMClient 实例
        chapter: 章节对象
        max_input_chars: 输入到 LLM 的最大字符数（超过则截断）

    Returns:
        SkillSection：提炼后的知识段落（与蒸馏 skill 格式兼容）
    """
    from novel_agent.utils.json_output import parse_json_safe

    content = chapter.content[:max_input_chars]
    prompt = _CHAPTER_SUMMARY_PROMPT.format(title=chapter.title, content=content)

    try:
        result = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )
        raw = result.get("content", "").strip()
    except Exception as e:
        logger.warning("章节 %d 提炼失败: %s", chapter.index, e)
        raw = ""

    # 解析 JSON（与蒸馏引擎一致）
    skill_data = parse_json_safe(raw) if raw else None
    if skill_data is None:
        logger.warning("章节 %d JSON 解析失败，使用兜底结构", chapter.index)
        skill_data = {
            "name": chapter.title,
            "description": "（LLM 输出未按 JSON 格式返回，已保留原始分析文本）",
            "features": [],
            "guidelines": [raw[:500]] if raw else [chapter.preview(300)],
            "tags": [],
            "glossary": [],
        }

    # 组装为 markdown 内容（与蒸馏 _compose_skill_content 格式对齐）
    display_name = skill_data.get("name") or chapter.title
    description = skill_data.get("description") or ""
    features = skill_data.get("features") or []
    guidelines = skill_data.get("guidelines") or []
    glossary = skill_data.get("glossary") or []
    tags = skill_data.get("tags") or []

    lines = [f"# {display_name}", ""]
    if description:
        lines += [description, ""]
    if features:
        lines.append("## 技法特征")
        for f in features:
            lines.append(f"- {f}")
        lines.append("")
    if guidelines:
        lines.append("## 写作规则（生成时必须遵守）")
        for i, g in enumerate(guidelines, 1):
            lines.append(f"{i}. {g}")
        lines.append("")
    if glossary:
        lines.append("## 关键术语")
        for term in glossary:
            lines.append(f"- {term}")
        lines.append("")
    lines.append("## 溯源")
    lines.append(f"- 来源：第 {chapter.index + 1} 章 {chapter.title}")

    summary = "\n".join(lines)
    keywords = tags + [display_name]

    return SkillSection(
        name=f"第{chapter.index + 1}章 {chapter.title}",
        content=summary,
        keywords=keywords,
        source_chapter=chapter.index,
    )


async def generate_overview(
    client,
    sections: list[SkillSection],
    book_title: str,
) -> tuple[str, str, str]:
    """生成全局概览 + 术语表 + 速查表。

    Returns:
        (overview, glossary, cheatsheet)
    """
    summaries = "\n\n---\n\n".join(
        f"**{s.name}**\n{s.content[:800]}" for s in sections
    )
    prompt = _OVERVIEW_PROMPT.format(summaries=summaries)

    try:
        result = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )
        overview_text = result.get("content", "").strip()
    except Exception as e:
        logger.warning("全局概览生成失败: %s", e)
        # 降级：拼接章节标题作为索引
        overview_text = f"### 章节索引\n" + "\n".join(
            f"- {s.name}" for s in sections
        )

    # 简单拆分 overview 中的术语表和速查表
    glossary = ""
    cheatsheet = ""
    if "### 核心术语表" in overview_text:
        parts = overview_text.split("### 核心术语表", 1)
        overview_text = parts[0].strip()
        rest = parts[1]
        if "### 速查表" in rest:
            sub = rest.split("### 速查表", 1)
            glossary = "### 核心术语表" + sub[0]
            cheatsheet = "### 速查表" + sub[1]
        else:
            glossary = "### 核心术语表" + rest

    return overview_text, glossary, cheatsheet


async def book_to_skill(
    client,
    full_text: str,
    book_title: str,
    description: str = "",
    max_chapters: int = 50,
    on_progress: callable = None,
) -> BookSkill:
    """完整拆书管线：文本 -> 章节拆分 -> LLM 逐章提炼 -> 生成索引。

    Args:
        client: LLMClient 实例
        full_text: 全书文本
        book_title: 书名
        description: 技能描述（可选）
        max_chapters: 最多处理多少章（防止超长书消耗过多 API）
        on_progress: 进度回调 fn(current, total, chapter_title)

    Returns:
        BookSkill：结构化技能包
    """
    # 1. 检测章节
    chapters = detect_chapters(full_text)
    logger.info("拆书「%s」：检测到 %d 章", book_title, len(chapters))

    if not chapters:
        raise ValueError("无法从文本中检测到章节结构，请检查文件内容")

    # 限制章节数量
    if len(chapters) > max_chapters:
        logger.warning("章节数 %d 超过上限 %d，只处理前 %d 章", len(chapters), max_chapters, max_chapters)
        chapters = chapters[:max_chapters]

    # 2. 逐章提炼
    sections: list[SkillSection] = []
    for i, ch in enumerate(chapters):
        if on_progress:
            on_progress(i + 1, len(chapters), ch.title)
        section = await summarize_chapter(client, ch)
        sections.append(section)

    # 3. 生成全局概览
    if on_progress:
        on_progress(len(chapters), len(chapters), "生成全局索引")
    overview, glossary, cheatsheet = await generate_overview(client, sections, book_title)

    # 4. 组装技能包
    slug = _slugify(book_title)
    desc = description or f"从《{book_title}》提炼的写作技法技能（{len(sections)}章）"

    return BookSkill(
        name=slug,
        description=desc,
        overview=overview,
        sections=sections,
        glossary=glossary,
        cheatsheet=cheatsheet,
    )
