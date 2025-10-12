#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAIL = False


def ok(message: str) -> None:
    print(f"OK {message}")


def fail(message: str) -> None:
    global FAIL
    FAIL = True
    print(f"FAIL {message}")


REQUIRED = [
    "services/strategy/__init__.py",
    "services/strategy/types.py",
    "services/strategy/regime.py",
    "services/strategy/universe.py",
    "services/strategy/equities.py",
    "services/strategy/options_strat.py",
    "services/strategy/engine.py",
    "services/execution/engine.py",
    "services/execution/types.py",
    "services/gateway/options.py",
    "services/risk/engine.py",
    "services/risk/state.py",
    "services/market/indicators.py",
    "tests/test_strategy_engine.py",
]


def must_exist() -> None:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        fail("missing files: " + ", ".join(missing))
    else:
        ok("Phase-6 files present")


def grep_tokens() -> None:
    engine = (ROOT / "services/strategy/engine.py").read_text(encoding="utf-8", errors="ignore")
    for token in [
        "class StrategyEngine",
        "async def on_bar",
        "ExecutionEngine",
        "OptionGateway",
    ]:
        if token not in engine:
            fail(f"engine.py missing token: {token}")

    equities = (ROOT / "services/strategy/equities.py").read_text(encoding="utf-8", errors="ignore")
    for token in ["class EquityStrategy", "OpeningRange", "RollingRSI", "on_bar"]:
        if token not in equities:
            fail(f"equities.py missing token: {token}")

    options = (ROOT / "services/strategy/options_strat.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    for token in ["class OptionStrategy", "on_bar"]:
        if token not in options:
            fail(f"options_strat.py missing token: {token}")

    gateway = (ROOT / "services/gateway/options.py").read_text(encoding="utf-8", errors="ignore")
    if "class OptionGateway" not in gateway:
        fail("options gateway not found")

    if not FAIL:
        ok("Symbol wiring present")


def _ensure_dotenv_stub() -> None:
    if "dotenv" in sys.modules:
        return
    stub = types.ModuleType("dotenv")

    def load_dotenv(*_args: object, **_kwargs: object) -> None:
        return None

    stub.load_dotenv = load_dotenv  # type: ignore[attr-defined]
    sys.modules["dotenv"] = stub


def import_sanity() -> None:
    sys.path.insert(0, str(ROOT))
    _ensure_dotenv_stub()
    try:
        import services.strategy.engine as strategy_engine
        import services.strategy.equities as equities
        import services.strategy.options_strat as options_strat
        import services.execution.engine as execution_engine
        import services.gateway.options as option_gateway
        import services.risk.engine as risk_engine
        import services.risk.state as risk_state
        import services.market.indicators as indicators
    except Exception as exc:  # pragma: no cover - defensive
        fail(f"import error: {exc}")
        return

    for module, cls in [
        (strategy_engine, "StrategyEngine"),
        (equities, "EquityStrategy"),
        (options_strat, "OptionStrategy"),
    ]:
        if not hasattr(module, cls):
            fail(f"{module.__name__} missing {cls}")

    for module, cls in [
        (execution_engine, "ExecutionEngine"),
        (option_gateway, "OptionGateway"),
        (risk_engine, "RiskManager"),
        (risk_state, "StateProvider"),
    ]:
        if not hasattr(module, cls):
            fail(f"{module.__name__} missing {cls}")

    for token in ["RollingRSI", "OpeningRange"]:
        if not hasattr(indicators, token):
            fail(f"indicators missing {token}")

    if not FAIL:
        ok("Imports & API shape OK")


def env_smoke() -> None:
    os.environ.setdefault("STRAT_EQUITY_ENABLED", "true")
    os.environ.setdefault("STRAT_OPTION_ENABLED", "true")
    os.environ.setdefault("STRAT_ORB_MIN", "30")
    os.environ.setdefault("STRAT_SENTI_MIN", "0.10")
    os.environ.setdefault("STRAT_COOLDOWN_SEC", "0")
    ok("Env defaults set for smoke")


def run_pytests() -> None:
    tests = [
        "tests/test_strategy_engine.py",
        "tests/test_options_select.py",
        "tests/test_execution_engine.py",
        "tests/test_risk_engine.py",
    ]
    cmd = [sys.executable, "-m", "pytest", "-q", *tests]
    print("$ " + " ".join(cmd))
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))
    result = subprocess.run(cmd, cwd=str(ROOT), check=False, env=env)
    if result.returncode != 0:
        fail("pytest failed")
    else:
        ok("pytest passed")


def main() -> None:
    must_exist()
    grep_tokens()
    import_sanity()
    env_smoke()
    run_pytests()
    print("\nSUMMARY: " + ("PASS ✅" if not FAIL else "FAIL ❌"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
