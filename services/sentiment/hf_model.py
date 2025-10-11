"""Lazy-loading HuggingFace FinBERT sentiment model."""
from __future__ import annotations

from typing import Dict

from services.sentiment.types import NewsItem, ScoredItem

_tokenizer = None
_pipeline = None


def _load(model_name: str) -> None:
    """Load the HF model on first use."""
    global _tokenizer, _pipeline
    if _pipeline is not None:
        return
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        TextClassificationPipeline,
    )

    _tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    _pipeline = TextClassificationPipeline(
        model=model,
        tokenizer=_tokenizer,
        return_all_scores=True,
        truncation=True,
    )


def infer(item: NewsItem, model_name: str) -> ScoredItem:
    """Infer sentiment for a news item using HuggingFace FinBERT."""
    _load(model_name)
    assert _pipeline is not None
    text = f"{item.title} {item.summary or ''}".strip()
    scores = _pipeline(text)[0]
    score_map: Dict[str, float] = {entry["label"].lower(): float(entry["score"]) for entry in scores}
    value = score_map.get("positive", 0.0) - score_map.get("negative", 0.0)
    if value > 0.1:
        label = "pos"
    elif value < -0.1:
        label = "neg"
    else:
        label = "neu"
    return ScoredItem(
        item=item,
        label=label,
        score=float(value),
        model=f"hf:{model_name}",
        features=score_map,
    )
