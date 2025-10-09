from __future__ import annotations

from typer.testing import CliRunner

from scripts.cli import app


def test_paper_command_runs(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("profile: paper\ndata:\n  symbols: []\n  timeframes: []\n  cache_path: data\nexecution:\n  venue: alpaca\n  time_in_force: day\nrisk_profile: safe\nrisk_presets: {}\n")
    runner = CliRunner()
    result = runner.invoke(app, ["paper", "--config", str(config)])
    assert result.exit_code == 0
    assert "Starting paper run" in result.stdout
