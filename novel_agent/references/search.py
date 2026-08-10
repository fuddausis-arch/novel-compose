"""参考资料检索：CSV 加载 + 关键词过滤 + 适用题材匹配。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


CSV_DIR = Path(__file__).parent / "csv"


def _load_csv(name: str) -> list[dict[str, str]]:
    path = CSV_DIR / f"{name}.csv"
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): (v or "").strip() for k, v in row.items()})
    return rows


def canonical_genre(genre_text: str) -> str:
    """根据用户输入的 genre 文本推断 canonical genre（返回关键词，如「玄幻修仙」）。

    优先精确匹配，匹配不到再回退到子串匹配。
    """
    text = (genre_text or "").strip().lower()
    rows = _load_csv("题材与调性推理")
    # 1. 精确匹配：输入与 canonical genre 完全一致
    for row in rows:
        canonical = row.get("关键词", "")
        if canonical and text == canonical.lower():
            return canonical
    # 2. 子串匹配（回退）：canonical genre 包含在输入中
    for row in rows:
        keywords = row.get("关键词", "")
        if all(k.strip().lower() in text for k in keywords.split("/") if k.strip()):
            return row.get("关键词", "")
    # 3. fallback：命中单个关键词（同时检查"适用题材"列）
    for row in rows:
        # 检查"关键词"列
        keywords = row.get("关键词", "").lower()
        for kw in keywords.split("/"):
            if kw.strip() and kw.strip() in text:
                return row.get("关键词", "")
        # 检查"适用题材"列（A6修复：之前完全忽略此列）
        applicable = row.get("适用题材", "").lower()
        for kw in applicable.split("/"):
            if kw.strip() and kw.strip() in text:
                return row.get("关键词", "")
    return "通用"


def genre_aliases(canonical_genre: str) -> set[str]:
    """获取某 canonical genre 的别名集合（关键词 + 适用题材拆词）。"""
    aliases = {canonical_genre}
    for row in _load_csv("题材与调性推理"):
        if row.get("关键词", "") == canonical_genre:
            for part in row.get("适用题材", "").split("/"):
                aliases.add(part.strip())
            break
    return aliases


class ReferenceSearch:
    """轻量级参考资料检索器。"""

    CSV_NAMES = [
        "题材与调性推理",
        "爽点与节奏",
        "桥段套路",
        "人设与关系",
        "场景写法",
        "写作技法",
        "命名规则",
        "金手指与设定",
        "裁决规则",
    ]

    def __init__(self):
        self._cache: dict[str, list[dict[str, str]]] = {}

    def _rows(self, name: str) -> list[dict[str, str]]:
        if name not in self._cache:
            self._cache[name] = _load_csv(name)
        return self._cache[name]

    def search(
        self,
        query: str,
        canonical_genre: str = "",
        skills: Iterable[str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, str]]:
        """按关键词和题材检索参考资料。"""
        query_words = [w.strip().lower() for w in query.replace(",", " ").split() if w.strip()]
        skills_set = set(skills or [])
        aliases = genre_aliases(canonical_genre) if canonical_genre else set()
        results: list[tuple[int, dict[str, str]]] = []

        for name in self.CSV_NAMES:
            for row in self._rows(name):
                # 技能过滤
                row_skill = row.get("适用技能", "全部")
                if skills_set and row_skill != "全部" and not (skills_set & set(row_skill.split("/"))):
                    continue

                # 题材过滤：全部 或 包含任一别名
                row_genres = row.get("适用题材", "全部")
                genre_match = False
                if row_genres == "全部":
                    genre_match = bool(canonical_genre)
                elif aliases:
                    genre_match = any(a in row_genres for a in aliases)

                # 关键词匹配
                text = " ".join([
                    row.get("关键词", ""),
                    row.get("核心摘要", ""),
                    row.get("详细展开", ""),
                    row.get("分类", ""),
                ]).lower()
                score = sum(2 for w in query_words if w in text)
                if genre_match:
                    score += 3
                if score > 0:
                    results.append((score, row))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def for_skill(self, skill: str, canonical_genre: str = "", limit: int = 8) -> list[dict[str, str]]:
        """为指定技能检索相关资料。"""
        return self.search(
            query="",
            canonical_genre=canonical_genre,
            skills=[skill],
            limit=limit,
        )

    def genre_profile(self, canonical_genre: str) -> dict[str, str]:
        """获取某 canonical genre 的题材画像。"""
        for row in self._rows("题材与调性推理"):
            if row.get("关键词", "") == canonical_genre:
                return row
        return {}

    def adjudication_rules(self, canonical_genre: str = "") -> list[dict[str, str]]:
        """获取裁决规则。"""
        rows = self._rows("裁决规则")
        if not canonical_genre:
            return rows
        aliases = genre_aliases(canonical_genre)
        return [
            r for r in rows
            if r.get("适用题材") == "全部"
            or any(a in r.get("适用题材", "") for a in aliases)
        ]
