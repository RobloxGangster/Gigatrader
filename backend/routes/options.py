from __future__ import annotations

from fastapi import APIRouter
from typing import Optional, Dict, Any
import pandas as pd

from core.runtime_flags import get_runtime_flags

router = APIRouter(prefix="/options", tags=["options"])


def _mock_chain(symbol: str, expiry: Optional[str]) -> pd.DataFrame:
    data = []
    for strike in range(80, 121, 5):
        data.append(
            {
                "symbol": symbol,
                "expiry": expiry or "2025-12-19",
                "strike": float(strike),
                "type": "call",
                "iv": 0.35,
                "oi": 500,
                "volume": 200,
                "bid": 1.0,
                "ask": 1.2,
            }
        )
        data.append(
            {
                "symbol": symbol,
                "expiry": expiry or "2025-12-19",
                "strike": float(strike),
                "type": "put",
                "iv": 0.36,
                "oi": 450,
                "volume": 180,
                "bid": 0.9,
                "ask": 1.1,
            }
        )
    return pd.DataFrame(data)


@router.get("/chain")
def options_chain(symbol: str, expiry: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns {"rows":[...]} where each row has at least:
      symbol, expiry, strike, type ('call'|'put'), iv, oi, volume, bid, ask
    Shape matches ui/services/models.OptionChain expectation.
    """
    mock_mode = get_runtime_flags().mock_mode
    df = None
    if not mock_mode:
        try:
            # Prefer adapter if available
            from services.options.adapter import get_option_chain  # type: ignore

            df = get_option_chain(symbol, expiry)
        except Exception:
            df = None
    if df is None:
        df = _mock_chain(symbol, expiry)

    required = ["symbol", "expiry", "strike", "type", "iv", "oi", "volume", "bid", "ask"]
    for col in required:
        if col not in df.columns:
            df[col] = None
    rows = df[required].to_dict(orient="records")
    return {"rows": rows}
