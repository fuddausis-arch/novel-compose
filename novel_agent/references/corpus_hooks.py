"""从本地小说语料库抽取真实章末钩子示例。

与 _load_random_human_chapter 的随机片段不同，本模块专注于：
- 解析完整小说文件的章节边界
- 按指定模式筛选章末结尾
- 返回少量真实 hook 样本供 prompt 使用
"""
from __future__ import annotations

import functools
import random
import re
from pathlib import Path
from typing import Iterable


CHAPTER_RE = re.compile(r"^第\s*[0-9一二三四五六七八九十百千零]+\s*章", re.MULTILINE)


def _find_corpus_dir() -> Path | None:
    """查找小说语料目录，兼容开发和打包模式。"""
    import sys as _sys

    candidates: list[Path] = []
    if getattr(_sys, "frozen", False):
        exe_dir = Path(_sys.executable).parent
        meipass = Path(getattr(_sys, "_MEIPASS", exe_dir))
        candidates.extend([
            meipass / "小说语料",
            exe_dir / "小说语料",
        ])
    else:
        _root = Path(__file__).resolve().parent.parent.parent
        candidates.append(_root / "小说语料")

    for d in candidates:
        if d.exists() and d.is_dir() and any(d.glob("*.txt")):
            return d
    return None


def _split_chapters(text: str) -> list[str]:
    """按「第X章」拆分完整小说文本。"""
    matches = list(CHAPTER_RE.finditer(text))
    chapters = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapters.append(text[start:end])
    return chapters


def _ending_type(tail: str) -> str | None:
    """简单规则判断结尾类型，返回 hook 类型标签。"""
    t = tail[-40:]
    if re.search(r'[\"\'"\'][^\"\'"\']{0,15}[？?][\"\'"\']$', tail):
        return "对话疑问"
    if re.search(r'[\"\'"\'][^\"\'"\']{0,15}[！!][\"\'"\']$', tail):
        return "对话感叹"
    if any(kw in t for kw in ["杀", "死", "尸体", "血"]):
        return "杀意/死亡"
    if any(kw in t for kw in ["来了", "追来", "逼近", "脚步声", "站在"]):
        return "敌人逼近"
    if any(kw in t for kw in ["知道了", "明白了", "意识到", "原来", "才发现"]):
        return "认知觉醒"
    if any(kw in t for kw in ["一定要", "必须", "绝不", "誓要", "等着"]):
        return "决心/誓言"
    if any(kw in t for kw in ["走去", "冲出", "杀出", "直奔", "站起身", "转过身"]):
        return "行动/动作"
    if any(kw in t for kw in ["真相", "秘密", "谎言", "隐瞒"]):
        return "真相/秘密"
    if tail.endswith(("？", "?")):
        return "内心疑问"
    if tail.endswith(("！", "!")):
        return "情绪爆发"
    if tail.endswith("……") or tail.endswith("..."):
        return "余韵省略"
    return "叙事推进"


@functools.lru_cache(maxsize=4)
def _load_all_endings(max_chars_per_example: int) -> tuple[tuple[str, str, str], ...]:
    """解析语料库并缓存章末样本（进程内只解析一次，避免每章生成都全量读 txt）。

    返回 (type, source, tail_text) 三元组列表；用 lru_cache 缓存，参数为 int 可哈希。
    """
    corpus_dir = _find_corpus_dir()
    if not corpus_dir:
        return ()

    all_endings: list[tuple[str, str, str]] = []
    # 优先使用预生成的 chapter_endings.json，避免读取全部 txt
    cache_file = corpus_dir / "chapter_endings.json"
    if cache_file.exists():
        import json as _json
        try:
            data = _json.loads(cache_file.read_text(encoding="utf-8"))
            for source, chapters in data.items():
                for ch in chapters:
                    tail = ch.get("tail", "")[-max_chars_per_example:].strip()
                    if len(tail) < 20:
                        continue
                    all_endings.append((
                        _ending_type(tail) or "其他",
                        Path(source).stem,
                        tail,
                    ))
        except Exception:
            pass

    # 没有缓存则降级实时解析（仅首次，结果缓存到模块级，后续直接复用）
    if not all_endings:
        novels = list(corpus_dir.glob("*.txt"))
        for novel in novels:
            try:
                text = novel.read_text(encoding="utf-8", errors="ignore")
                chapters = _split_chapters(text)
                for ch in chapters:
                    ch = ch.strip().replace("\n", " ")
                    if len(ch) < 100:
                        continue
                    tail = ch[-max_chars_per_example:].strip()
                    all_endings.append((
                        _ending_type(tail) or "其他",
                        novel.stem,
                        tail,
                    ))
            except Exception:
                continue

    return tuple(all_endings)


def load_corpus_hook_examples(
    preferred_types: Iterable[str] | None = None,
    total: int = 6,
    max_chars_per_example: int = 120,
) -> list[dict[str, str]]:
    """从本地语料库抽取真实章末钩子示例。

    Args:
        preferred_types: 偏好的 hook 类型，如 ["杀意/死亡", "认知觉醒"]。
                         为空时随机返回各类样本。
        total: 返回样本总数。
        max_chars_per_example: 每条样本最大长度。

    Returns:
        每条包含 {type, source, text} 的示例列表。
    """
    endings = _load_all_endings(max_chars_per_example)
    if not endings:
        return []

    all_endings = [
        {"type": t, "source": s, "text": text}
        for t, s, text in endings
    ]

    preferred_set = set(preferred_types or [])
    if preferred_set:
        preferred = [e for e in all_endings if e["type"] in preferred_set]
        others = [e for e in all_endings if e["type"] not in preferred_set]
        examples = preferred[:total]
        if len(examples) < total:
            examples.extend(random.sample(others, min(total - len(examples), len(others))))
    else:
        examples = random.sample(all_endings, min(total, len(all_endings)))

    return examples
