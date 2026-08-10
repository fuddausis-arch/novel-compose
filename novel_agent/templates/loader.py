"""题材模板与提示词模板加载器。"""
from __future__ import annotations

from pathlib import Path
from string import Template


GENRES_DIR = Path(__file__).parent / "genres"
PROMPTS_DIR = Path(__file__).parent / "prompts"


def list_genres() -> list[str]:
    """列出所有可用 canonical genre 名称。"""
    return sorted([p.stem for p in GENRES_DIR.glob("*.md")])


class GenreLoader:
    """加载指定 canonical genre 的 markdown 模板。"""

    def __init__(self):
        self._cache: dict[str, str] = {}

    def load(self, canonical_genre: str) -> str:
        """加载模板内容，找不到返回空串。"""
        if canonical_genre in self._cache:
            return self._cache[canonical_genre]
        path = GENRES_DIR / f"{canonical_genre}.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        self._cache[canonical_genre] = text
        return text

    def exists(self, canonical_genre: str) -> bool:
        return (GENRES_DIR / f"{canonical_genre}.md").exists()

    def _extract_section(self, canonical_genre: str, marker: str) -> str:
        """提取模板中指定 ## 标题下的内容。"""
        text = self.load(canonical_genre)
        if not text:
            return ""
        start = text.find(marker)
        if start < 0:
            return ""
        next_heading = text.find("\n## ", start + len(marker))
        if next_heading < 0:
            return text[start:].strip()
        return text[start:next_heading].strip()

    def extract_style_benchmark(self, canonical_genre: str) -> str:
        """提取模板中的 ## 文风标杆 部分，用于注入写作 prompt。"""
        return self._extract_section(canonical_genre, "## 文风标杆")

    def extract_core_selling_point(self, canonical_genre: str) -> str:
        """提取模板中的 ## 核心卖点 部分。"""
        return self._extract_section(canonical_genre, "## 核心卖点")

    def extract_recommended_constraints(self, canonical_genre: str) -> str:
        """提取模板中的 ## 推荐约束包 部分。"""
        return self._extract_section(canonical_genre, "## 推荐约束包")

    def extract_rule_types(self, canonical_genre: str) -> str:
        """提取模板中的世界观/规则/力量体系部分。

        A7修复：不同题材模板用了不同标题（世界观与规则/世界观与力量体系/世界观与社会结构），
        改为正则匹配"## 世界观与"前缀，兼容所有变体。
        """
        import re
        text = self.load(canonical_genre)
        if not text:
            return ""
        # 正则匹配所有以"## 世界观与"开头的段落
        pattern = r'(## 世界观与[^\n]*\n(?:.*\n)*?)(?=\n## |\Z)'
        matches = re.findall(pattern, text)
        if matches:
            return "\n".join(matches)
        return ""

    def extract_rhythm_suggestions(self, canonical_genre: str) -> str:
        """提取模板中的 ## 节奏建议 部分。"""
        return self._extract_section(canonical_genre, "## 节奏建议")

    def extract_classic_hooks(self, canonical_genre: str) -> str:
        """提取模板中的 ## 经典爽点套路 部分。"""
        return self._extract_section(canonical_genre, "## 经典爽点套路")

    def extract_genre_context(self, canonical_genre: str) -> str:
        """提取除文风标杆和实体标签扩展外的全部题材上下文。"""
        text = self.load(canonical_genre)
        if not text:
            return ""
        # 去掉实体标签扩展部分（对 writer 无用）
        entity_marker = "## 实体标签扩展"
        entity_start = text.find(entity_marker)
        if entity_start >= 0:
            text = text[:entity_start].strip()
        return text


class PromptLoader:
    """加载并渲染提示词模板。"""

    def __init__(self):
        self._cache: dict[str, Template] = {}

    def load(self, name: str) -> Template:
        """加载模板文件，返回 string.Template。"""
        if name in self._cache:
            return self._cache[name]
        path = PROMPTS_DIR / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"提示词模板不存在：{path}")
        template = Template(path.read_text(encoding="utf-8"))
        self._cache[name] = template
        return template

    def render(self, name: str, **kwargs) -> str:
        """加载模板并用 kwargs 渲染。"""
        return self.load(name).safe_substitute(**kwargs)
