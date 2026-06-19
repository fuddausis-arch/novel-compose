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
