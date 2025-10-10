from __future__ import annotations

from typer.testing import CliRunner

from app.cli import app


def test_paper_command_runs(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "{"  # JSON is valid YAML and works with the fallback loader
        '"profile": "paper",'
        '"risk_profile": "safe",'
        '"data": {"symbols": ["TEST"], "timeframes": ["1Min"], "cache_path": "data"},'
        '"execution": {"venue": "alpaca", "time_in_force": "day"},'
        '"risk_presets": {'
        '  "safe": {'
        '    "name": "safe", "daily_loss_limit": 1000, "per_trade_loss_limit": 200,'
        '    "max_exposure": 10000, "max_positions": 5,'
        '    "options_max_notional_per_expiry": 5000, "min_option_liquidity": 50,'
        '    "delta_bounds": [0.3, 0.35], "vega_limit": 0.5, "theta_limit": 0.5'
        '  }'
        '}'
        "}"
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "paper",
            "--config",
            str(config),
            "--max-iterations",
            "2",
            "--bar-interval",
            "0",
        ],
    )
    assert result.exit_code == 0
    assert "Simulated fill" in result.stdout
