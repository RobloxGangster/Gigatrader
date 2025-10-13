import re

_POS = {
    "beat","beats","beating","surge","surged","surging","soar","soared","soaring",
    "rise","rises","rising","gain","gains","gained","record","outperform","upgrade","bullish",
    "strong","positive","optimistic","acceleration","profit","profits","profitability",
    "exceed","exceeds","exceeded","above","tops"
}
_NEG = {
    "miss","misses","missed","fall","falls","fell","falling","drop","drops","dropped",
    "plunge","plunged","plunging","decline","declined","declining","cut","cuts","cutting",
    "downgrade","bearish","weak","negative","pessimistic","loss","losses","bankruptcy","probe",
    "investigation","recall","lawsuit","fine","fines","penalty","penalties","fraud"
}

_TOKEN = re.compile(r"[A-Za-z]+")

def heuristic_score(headline: str, summary: str = "") -> float:
    """
    Very light lexicon score in [-1, 1].
    """
    text = f"{headline} {summary}".lower()
    words = _TOKEN.findall(text)
    if not words:
        return 0.0
    pos = sum(1 for w in words if w in _POS)
    neg = sum(1 for w in words if w in _NEG)
    if pos == 0 and neg == 0:
        return 0.0
    raw = (pos - neg) / max(1, (pos + neg))
    # clamp to [-1,1]
    return max(-1.0, min(1.0, raw))
