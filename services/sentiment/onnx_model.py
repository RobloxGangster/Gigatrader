"""ONNX runtime wrapper for FinBERT models."""

from __future__ import annotations

import math
from typing import Dict

try:  # pragma: no cover - optional heavy dependency
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - lightweight fallback
    np = None  # type: ignore[assignment]

_tokenizer = None
_session = None


def _load(path: str) -> None:
    """Load the ONNX session on first use."""
    global _tokenizer, _session
    if _session is not None:
        return
    try:
        import onnxruntime as ort  # type: ignore
        from transformers import AutoTokenizer  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dep guard
        raise RuntimeError("onnx runtime dependencies are unavailable") from exc

    _tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
    _session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def _softmax(values):  # type: ignore[override]
    if np is not None:
        shifted = values - np.max(values)
        exp_values = np.exp(shifted)
        return exp_values / exp_values.sum(-1, keepdims=True)
    # Lightweight fallback for environments without NumPy.
    arr = list(values)
    maximum = max(arr)
    exps = [math.exp(v - maximum) for v in arr]
    total = sum(exps) or 1.0
    return [val / total for val in exps]


def _fallback_scores(text: str) -> Dict[str, float]:
    """Deterministic heuristic used when ONNX runtime is unavailable."""

    positive_keywords = {"beat", "growth", "surge", "record", "strong"}
    negative_keywords = {"miss", "drop", "loss", "fall", "weak"}
    tokens = text.lower().split()
    pos_hits = sum(token in positive_keywords for token in tokens)
    neg_hits = sum(token in negative_keywords for token in tokens)
    total = max(1, pos_hits + neg_hits)
    pos = 0.5 + (pos_hits - neg_hits) / (2 * total)
    neg = 1.0 - pos
    neu = max(0.0, 1.0 - abs(pos_hits - neg_hits) / total)
    # Normalize to ensure the distribution sums to 1.0
    denom = pos + neg + neu or 1.0
    return {
        "negative": float(neg / denom),
        "neutral": float(neu / denom),
        "positive": float(pos / denom),
    }


def infer(text: str, path: str) -> Dict[str, float]:
    """Infer sentiment probabilities using an ONNX model."""
    try:
        _load(path)
    except RuntimeError:
        return _fallback_scores(text)

    if np is None:
        return _fallback_scores(text)

    assert _tokenizer is not None and _session is not None
    tokens = _tokenizer(text, return_tensors="np", truncation=True)
    inputs = {key: value for key, value in tokens.items()}
    logits = _session.run(None, inputs)[0][0]
    probs = _softmax(logits)
    return {
        "negative": float(probs[0]),
        "neutral": float(probs[1]),
        "positive": float(probs[2]),
    }
