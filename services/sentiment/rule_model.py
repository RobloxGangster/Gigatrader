"""Simple rule-based sentiment scoring."""

from __future__ import annotations

from services.sentiment.types import NewsItem, ScoredItem

POS = {
    "beats",
    "surge",
    "upgrade",
    "record",
    "strong",
    "profit",
    "raises",
    "growth",
    "win",
    "tops",
}

NEG = {
    "miss",
    "fall",
    "downgrade",
    "recall",
    "fraud",
    "loss",
    "cut",
    "probe",
    "lawsuit",
    "reduce",
    "plunge",
    "slump",
}


def score_text(text: str) -> float:
    """Score text by counting positive and negative keywords."""
    lowered = text.lower()
    pos_hits = sum(1 for word in POS if word in lowered)
    neg_hits = sum(1 for word in NEG if word in lowered)
    if pos_hits == neg_hits == 0:
        return 0.0
    raw = (pos_hits - neg_hits) / 4.0
    return max(-1.0, min(1.0, raw))


def infer(item: NewsItem) -> ScoredItem:
    """Infer sentiment for a news item using the rule model."""
    text = f"{item.title} {item.summary or ''}".strip()
    score = score_text(text)
    if score > 0.1:
        label = "pos"
    elif score < -0.1:
        label = "neg"
    else:
        label = "neu"
    return ScoredItem(
        item=item,
        label=label,
        score=score,
        model="rule",
        features={"pos_neg": score},
    )
