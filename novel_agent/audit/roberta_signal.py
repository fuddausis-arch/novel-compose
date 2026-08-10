"""深度 AI 味检测：MPU 中文检测模型（北大华为 AIGC-Detector，ICLR'24 Spotlight）。

与 audit/ai_detect.py 的关系：
- ai_detect.py   = 规则 + 统计信号（快、零成本、抓显式 AI 味词）
- 本模块         = 专门训练的分类模型（最准，针对 DeepSeek/GPT-4 等最新 LLM）

主模型：YuchuanTian/AIGC_text_detector_zhv3（chinese-roberta-wwm-ext 微调，官方中文 v3）
  - 实测 label1 = AI 概率（AI 文本 0.9997 / 人类文本 0.1014）
  - CPU 推理约 0.01s/段，加载一次全局复用
备选模型：Hello-SimpleAI/chatgpt-detector-roberta-chinese（若 zhv3 不存在则回退）

对长文按 token 上限分段推理，返回：全文 AI 概率、判定、逐段概率（定位 AI 味最重的段落）。

模型懒加载（首次调用才加载，约 1-3 秒）。
模型文件位置：{project_data}/models/AIGC_detector_zhv3
下载：pip install modelscope && snapshot_download('YuchuanTian/AIGC_text_detector_zhv3')
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_REPO = "YuchuanTian/AIGC_text_detector_zhv3"
_FALLBACK_REPO = "Hello-SimpleAI/chatgpt-detector-roberta-chinese"

# 每段最大 token（roberta 输入上限 512，留余量）
_MAX_SEG_TOKENS = 460
# 判定阈值
_AI_HIGH = 0.65   # >= 判为 AI
_AI_LOW = 0.35    # <= 判为人类


def _model_dir() -> Path:
    """模型目录：优先微调版（真人网文领域适配），其次原版 zhv3。

    注意：不再回退 chatgpt-detector-roberta-chinese（实测对网文无区分力，
    会把 AI 文本也判成人类，静默失效）；两版 zhv3 都不在时返回不存在的路径，
    由 detect_deep 捕获后返回"模型未就绪"，走两层降级。
    """
    from novel_agent.config import load_config
    base = load_config().project_data_dir / "models"
    for name in ("AIGC_detector_zhv3_finetuned", "AIGC_detector_zhv3"):
        p = base / name
        if (p / "config.json").exists():
            return p
    return base / "AIGC_detector_zhv3"


@lru_cache(maxsize=1)
def _get_pipeline():
    """懒加载模型 + 分词器（全局只加载一次）。"""
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        TextClassificationPipeline,
    )

    model_path = _model_dir()
    if not (model_path / "config.json").exists():
        raise FileNotFoundError(
            f"深度检测模型未下载（{model_path}）。请先下载 "
            f"YuchuanTian/AIGC_text_detector_zhv3（ModelScope 国内源）"
        )
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_path))
    model.eval()
    pipe = TextClassificationPipeline(model=model, tokenizer=tokenizer, top_k=None)
    logger.info("深度 AI 检测模型已加载: %s", model_path)
    return pipe


def _split_segments(text: str, tokenizer, max_tokens: int = _MAX_SEG_TOKENS) -> list[str]:
    """把长文按句切块，合并到不超过 max_tokens 的段。"""
    import re

    if not text:
        return []
    sentences = [s for s in re.split(r"(?<=[。！？!?；;])", text) if s.strip()]
    segments: list[str] = []
    cur = ""
    for s in sentences:
        if not cur:
            cur = s
            continue
        cand = cur + s
        if len(tokenizer.encode(cand, add_special_tokens=False)) <= max_tokens:
            cur = cand
        else:
            segments.append(cur)
            cur = s
    if cur:
        segments.append(cur)
    return [s for s in segments if s.strip()]


def _parse_probability(result) -> dict:
    """把 pipeline 输出转成 {label: prob}。

    top_k=None 时输出是嵌套列表 [[{label,score}, ...]]（样本 × topk），
    需要先解一层；单样本时取第一项。
    """
    probs: dict[str, float] = {}
    items = result
    if isinstance(result, list) and result and isinstance(result[0], list):
        items = result[0] if len(result) == 1 else [it for sub in result for it in sub]
    for item in items:
        if isinstance(item, dict) and "label" in item and "score" in item:
            probs[str(item["label"])] = float(item["score"])
    return probs


def _ai_probability(probs: dict[str, float]) -> float:
    """从 label 概率里取 AI 概率。

    zhv3 实测：LABEL_1 = AI，LABEL_0 = 人类（无 id2label，用顺序兜底）。
    """
    # 优先按名字识别
    ai_p = probs.get("AI", probs.get("LABEL_1", 0.0))
    if ai_p:
        return ai_p
    # 兜底：1 - 人类概率
    human_p = probs.get("Human", probs.get("LABEL_0", 0.0))
    return 1.0 - human_p if human_p else 0.5


def detect_deep(text: str) -> dict:
    """深度检测：返回 MPU 模型的 AI 概率报告。

    Returns:
        {
            "available": True,
            "ai_probability": 0-1,   # 全文 AI 概率（段落按字数加权）
            "verdict": "AI"|"Mixed"|"Human",
            "ai_level": "明显AI味"|"疑似AI味"|"自然",
            "segments": [{"text": 段, "ai_probability": 0-1, "chars": N}, ...],
            "summary": str,
            "model": "AIGC_text_detector_zhv3",
            "error": None,
        }
    """
    try:
        pipe = _get_pipeline()
        tokenizer = pipe.tokenizer
    except Exception as e:
        logger.warning("深度检测模型不可用: %s", e)
        return {
            "available": False,
            "ai_probability": None,
            "verdict": "unavailable",
            "ai_level": "模型未就绪",
            "segments": [],
            "summary": f"深度检测模型不可用（{e}）。请先下载 AIGC_detector_zhv3。",
            "model": MODEL_REPO,
            "error": str(e),
        }

    segments = _split_segments(text, tokenizer)
    if not segments:
        return {
            "available": True, "ai_probability": 0.0, "verdict": "Human",
            "ai_level": "自然", "segments": [], "summary": "文本为空，无法检测",
            "model": MODEL_REPO, "error": None,
        }

    seg_reports: list[dict] = []
    total_chars = 0
    weighted = 0.0
    for seg in segments:
        try:
            result = pipe(seg, truncation=True, max_length=512)
            probs = _parse_probability(result)
            ai_p = _ai_probability(probs)
            chars = len(seg)
            seg_reports.append({"text": seg[:120], "ai_probability": round(ai_p, 4), "chars": chars})
            total_chars += chars
            weighted += ai_p * chars
        except Exception as e:
            logger.warning("深度检测某段失败: %s", e)

    if total_chars == 0:
        return {
            "available": True, "ai_probability": 0.0, "verdict": "Human",
            "ai_level": "自然", "segments": [], "summary": "模型推理失败",
            "model": MODEL_REPO, "error": "inference_failed",
        }

    ai_prob = weighted / total_chars
    if ai_prob >= _AI_HIGH:
        verdict, level = "AI", "明显AI味"
    elif ai_prob <= _AI_LOW:
        verdict, level = "Human", "自然"
    else:
        verdict, level = "Mixed", "疑似AI味"

    top = sorted(seg_reports, key=lambda s: s["ai_probability"], reverse=True)[:5]
    summary = (
        f"深度检测：AI 概率 {ai_prob:.0%}（{level}），全文 {len(segments)} 段；"
        + (f"最可疑段落 AI 概率最高达 {top[0]['ai_probability']:.0%}" if top else "所有段落均倾向人类")
    )

    return {
        "available": True,
        "ai_probability": round(ai_prob, 4),
        "verdict": verdict,
        "ai_level": level,
        "segments": seg_reports,
        "summary": summary,
        "model": MODEL_REPO,
        "error": None,
    }
