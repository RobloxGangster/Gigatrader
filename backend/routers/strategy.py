"""Strategy configuration endpoints."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .deps import get_strategy_registry

router = APIRouter()


class StrategyConfigPatch(BaseModel):
    """Allow partial updates from the UI without breaking legacy clients."""

    enable: Dict[str, bool] | None = None
    thresholds: Dict[str, float] | None = None
    universe: list[str] | None = None
    pacing_sec: int | None = None

    # Legacy payload compatibility
    preset: str | None = None
    enabled: bool | None = None
    strategies: Dict[str, bool] | None = None
    confidence_threshold: float | None = None
    expected_value_threshold: float | None = None
    cooldown_sec: int | None = None
    pacing_per_minute: int | None = None
    dry_run: bool | None = None

    model_config = ConfigDict(extra="allow")


@router.get("/strategy/config")
def strategy_config() -> Any:
    sr = get_strategy_registry()
    try:
        return sr.snapshot()
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=500, detail=f"strategy_config: {exc}") from exc


@router.post("/strategy/config")
def strategy_config_update(patch: StrategyConfigPatch) -> Any:
    sr = get_strategy_registry()
    try:
        return sr.apply_patch(patch.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001 - surfaced to client
        raise HTTPException(status_code=400, detail=f"strategy_config_update: {exc}") from exc
