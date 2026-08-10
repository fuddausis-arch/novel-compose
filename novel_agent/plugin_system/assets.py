"""Skill / Rule / 预设短语资产化（移植自 DeterminFlow 资产化概念）。

把散落在 project_data 下的三类资产（skills/*.json、rules/rules.json、
preset_phrases.json）打包为可移植的 .naassets（zip）资产包，支持：
- export_assets: 导出为资产包
- import_assets: 从资产包导入（merge/overwrite 两种策略）
- 资产包可随 Plugin 一起交付（放入插件 resources/ 目录）

资产包格式 .naassets = zip，内含：
  manifest.json     {"kind": "novel-agent-assets", "version": 1, "counts": {...}}
  skills/<name>.json
  rules/rules.json
  preset_phrases.json
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from novel_agent.config import load_config

logger = logging.getLogger(__name__)

ASSETS_SUFFIX = ".naassets"
_ASSETS_KIND = "novel-agent-assets"
_ASSETS_VERSION = 1
_MAX_ASSETS_BYTES = 16 * 1024 * 1024


class AssetsError(RuntimeError):
    """资产包导出/导入失败。"""


def _assets_layout() -> dict[str, Path]:
    """返回三类资产在磁盘上的位置。"""
    cfg = load_config()
    base = cfg.project_data_dir
    return {
        "skills_dir": base / "skills",
        "rules_file": base / "rules" / "rules.json",
        "phrases_file": base / "preset_phrases.json",
    }


def export_assets(output_path: str | Path, *, include: tuple[str, ...] = ("skills", "rules", "preset_phrases")) -> dict[str, Any]:
    """导出资产包。

    Args:
        output_path: 输出 .naassets 路径
        include: 要导出的资产类型子集

    Returns:
        {"status": "exported", "path": ..., "counts": {...}}
    """
    layout = _assets_layout()
    counts: dict[str, int] = {"skills": 0, "rules": 0, "preset_phrases": 0}
    output_path = Path(output_path).resolve()

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if "skills" in include and layout["skills_dir"].exists():
            for skill_file in sorted(layout["skills_dir"].glob("*.json")):
                zf.write(skill_file, f"skills/{skill_file.name}")
                counts["skills"] += 1
        if "rules" in include and layout["rules_file"].exists():
            zf.write(layout["rules_file"], "rules/rules.json")
            try:
                with open(layout["rules_file"], encoding="utf-8") as f:
                    counts["rules"] = len(json.load(f))
            except Exception:
                counts["rules"] = 1
        if "preset_phrases" in include and layout["phrases_file"].exists():
            zf.write(layout["phrases_file"], "preset_phrases.json")
            try:
                with open(layout["phrases_file"], encoding="utf-8") as f:
                    data = json.load(f)
                counts["preset_phrases"] = len(data) if isinstance(data, list) else 1
            except Exception:
                counts["preset_phrases"] = 1

        manifest = {
            "kind": _ASSETS_KIND,
            "version": _ASSETS_VERSION,
            "counts": counts,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    logger.info("资产包已导出: %s counts=%s", output_path, counts)
    return {"status": "exported", "path": str(output_path), "counts": counts}


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    if "manifest.json" not in zf.namelist():
        raise AssetsError("资产包缺少 manifest.json")
    with zf.open("manifest.json") as f:
        manifest = json.loads(f.read().decode("utf-8"))
    if manifest.get("kind") != _ASSETS_KIND:
        raise AssetsError(f"不是 NovelAgent 资产包: kind={manifest.get('kind')!r}")
    if int(manifest.get("version", 0)) > _ASSETS_VERSION:
        raise AssetsError(f"资产包版本过新: {manifest.get('version')}")
    return manifest


def _safe_name(name: str) -> PurePosixPath:
    rel = PurePosixPath(name.replace("\\", "/"))
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise AssetsError(f"资产包含非法路径: {name}")
    return rel


def inspect_assets(package_path: str | Path) -> dict[str, Any]:
    """查看资产包内容摘要（不导入）。"""
    package_path = Path(package_path).resolve()
    if not package_path.exists():
        raise AssetsError(f"资产包不存在: {package_path}")
    try:
        with zipfile.ZipFile(package_path) as zf:
            manifest = _read_manifest(zf)
            return {"status": "ok", "manifest": manifest,
                    "files": [n for n in zf.namelist() if n != "manifest.json"]}
    except zipfile.BadZipFile as e:
        raise AssetsError(f"不是合法的资产包: {e}") from e


def import_assets(
    package_path: str | Path,
    *,
    strategy: str = "merge",
) -> dict[str, Any]:
    """导入资产包。

    Args:
        package_path: .naassets 路径
        strategy: "merge"（同名跳过）或 "overwrite"（同名覆盖）

    Returns:
        {"status": "imported", "imported": {...}, "skipped": {...}}
    """
    if strategy not in ("merge", "overwrite"):
        raise AssetsError(f"未知导入策略: {strategy}")

    package_path = Path(package_path).resolve()
    if not package_path.exists():
        raise AssetsError(f"资产包不存在: {package_path}")
    if package_path.stat().st_size > _MAX_ASSETS_BYTES:
        raise AssetsError(f"资产包超过大小上限 {_MAX_ASSETS_BYTES}")

    layout = _assets_layout()
    imported: dict[str, int] = {"skills": 0, "rules": 0, "preset_phrases": 0}
    skipped: dict[str, int] = {"skills": 0, "rules": 0, "preset_phrases": 0}

    try:
        zf = zipfile.ZipFile(package_path)
    except zipfile.BadZipFile as e:
        raise AssetsError(f"不是合法的资产包: {e}") from e

    with zf:
        _read_manifest(zf)

        # ── skills：逐文件导入 ──
        skills_dir = layout["skills_dir"]
        skills_dir.mkdir(parents=True, exist_ok=True)
        for name in zf.namelist():
            if not name.startswith("skills/") or not name.endswith(".json"):
                continue
            rel = _safe_name(name)
            skill_name = rel.name
            dest = skills_dir / skill_name
            if dest.exists() and strategy == "merge":
                skipped["skills"] += 1
                continue
            with zf.open(name) as f:
                data = f.read()
            # 校验 JSON 合法
            try:
                json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("跳过非法 skill JSON %s: %s", name, e)
                skipped["skills"] += 1
                continue
            dest.write_bytes(data)
            imported["skills"] += 1

        # ── rules：列表级合并 ──
        if "rules/rules.json" in zf.namelist():
            with zf.open("rules/rules.json") as f:
                incoming = json.loads(f.read().decode("utf-8"))
            if isinstance(incoming, list):
                layout["rules_file"].parent.mkdir(parents=True, exist_ok=True)
                existing: list[dict] = []
                if layout["rules_file"].exists():
                    with open(layout["rules_file"], encoding="utf-8") as f:
                        existing = json.load(f) or []
                existing_names = {r.get("name") for r in existing if isinstance(r, dict)}
                for rule in incoming:
                    if not isinstance(rule, dict) or not rule.get("name"):
                        continue
                    if rule["name"] in existing_names:
                        if strategy == "overwrite":
                            existing = [r for r in existing
                                        if not (isinstance(r, dict) and r.get("name") == rule["name"])]
                            existing.append(rule)
                            imported["rules"] += 1
                        else:
                            skipped["rules"] += 1
                    else:
                        existing.append(rule)
                        existing_names.add(rule["name"])
                        imported["rules"] += 1
                with open(layout["rules_file"], "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)

        # ── preset_phrases：列表级合并 ──
        if "preset_phrases.json" in zf.namelist():
            with zf.open("preset_phrases.json") as f:
                incoming = json.loads(f.read().decode("utf-8"))
            if isinstance(incoming, list):
                existing_p: list[dict] = []
                if layout["phrases_file"].exists():
                    with open(layout["phrases_file"], encoding="utf-8") as f:
                        existing_p = json.load(f) or []
                existing_texts = {p.get("text") for p in existing_p if isinstance(p, dict)}
                for phrase in incoming:
                    if not isinstance(phrase, dict) or not phrase.get("text"):
                        continue
                    if phrase["text"] in existing_texts:
                        if strategy == "overwrite":
                            existing_p = [p for p in existing_p
                                          if not (isinstance(p, dict) and p.get("text") == phrase["text"])]
                            existing_p.append(phrase)
                            imported["preset_phrases"] += 1
                        else:
                            skipped["preset_phrases"] += 1
                    else:
                        existing_p.append(phrase)
                        existing_texts.add(phrase["text"])
                        imported["preset_phrases"] += 1
                with open(layout["phrases_file"], "w", encoding="utf-8") as f:
                    json.dump(existing_p, f, ensure_ascii=False, indent=2)

    logger.info("资产包已导入: %s imported=%s skipped=%s", package_path, imported, skipped)
    return {"status": "imported", "imported": imported, "skipped": skipped}
