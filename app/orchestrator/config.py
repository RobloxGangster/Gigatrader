from __future__ import annotations

"""Utilities for orchestrator, strategy, and risk configuration loading."""

import logging
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError as exc:  # pragma: no cover - import guard
    raise RuntimeError(
        "PyYAML is required but not installed. Add 'PyYAML>=6.0.1' to requirements "
        "and reinstall your environment."
    ) from exc

LOGGER = logging.getLogger(__name__)
_CONFIG_ROOTS: tuple[Path, ...] = (Path("config"), Path("configs"), Path("."))


def _candidate_paths(filename: str) -> Iterable[Path]:
    for root in _CONFIG_ROOTS:
        candidate = root / filename if root != Path(".") else Path(filename)
        yield candidate


def load_yaml_safe(path: str | Path) -> dict[str, Any]:
    """Load YAML configuration as a dictionary using safe parsing."""

    target = Path(path)
    with target.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if isinstance(payload, dict):
        return dict(payload)
    raise ValueError(f"Expected mapping data in {target}, received {type(payload).__name__}")


def _load_named_config(filename: str) -> dict[str, Any]:
    for candidate in _candidate_paths(filename):
        if not candidate.exists():
            continue
        return load_yaml_safe(candidate)
    raise FileNotFoundError(filename)


def try_load_orchestrator_config() -> dict[str, Any]:
    """Best-effort load of orchestrator configuration."""

    try:
        return _load_named_config("orchestrator.yaml")
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to load orchestrator config: %s", exc)
        raise


def try_load_strategy_config() -> dict[str, Any]:
    """Best-effort load of strategy configuration overrides."""

    try:
        return _load_named_config("strategy.yaml")
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to load strategy config: %s", exc)
        raise


def try_load_risk_config() -> dict[str, Any]:
    """Best-effort load of risk configuration overrides."""

    try:
        return _load_named_config("risk.yaml")
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to load risk config: %s", exc)
        raise
