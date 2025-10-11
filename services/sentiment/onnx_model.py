"""ONNX runtime wrapper for FinBERT models."""
from __future__ import annotations

from typing import Dict

import numpy as np

_tokenizer = None
_session = None


def _load(path: str) -> None:
    """Load the ONNX session on first use."""
    global _tokenizer, _session
    if _session is not None:
        return
    from transformers import AutoTokenizer

    import onnxruntime as ort

    _tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
    _session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exp_values = np.exp(shifted)
    return exp_values / exp_values.sum(-1, keepdims=True)


def infer(text: str, path: str) -> Dict[str, float]:
    """Infer sentiment probabilities using an ONNX model."""
    _load(path)
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
