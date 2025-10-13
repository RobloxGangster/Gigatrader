"""Smoke tests for Streamlit UI using streamlit.testing."""

from __future__ import annotations

from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")



def _run_app() -> "streamlit_testing.AppTest":
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    at = streamlit_testing.AppTest.from_file(str(app_path))
    at.run(timeout=10)
    return at


def test_app_loads_mock_mode(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_MODE", "true")
    at = _run_app()
    assert any("Mock mode" in str(getattr(element, "value", element)) for element in at.sidebar)


def test_start_stop_buttons(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_MODE", "true")
    at = _run_app()
    control_button = next(widget for widget in at.button if widget.label == "Start Paper")
    control_button.click().run()
    stop_button = next(widget for widget in at.button if widget.label == "Stop")
    stop_button.click().run()


def test_option_chain_filter(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_MODE", "true")
    at = _run_app()
    nav = next(widget for widget in at.selectbox if widget.label == "Navigation")
    nav.select("Option Chain").run()
    df_value = at.dataframe[0].value
    if hasattr(df_value, "data"):
        df = df_value.data
    else:
        df = df_value
    assert all(row["is_liquid"] for _, row in df.iterrows())


def test_repro_bundle_creation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.example.yaml").write_text("sample: config")
    (tmp_path / "RISK_PRESETS.md").write_text("presets")
    fixtures_src = Path(__file__).resolve().parents[1] / "fixtures"
    fixtures_dst = tmp_path / "fixtures"
    fixtures_dst.mkdir()
    for file in fixtures_src.iterdir():
        fixtures_dst.joinpath(file.name).write_text(file.read_text())
    (tmp_path / "ui").mkdir(exist_ok=True)

    at = _run_app()
    nav = next(widget for widget in at.selectbox if widget.label == "Navigation")
    nav.select("Logs").run()
    button = next(widget for widget in at.button if widget.label == "Create Repro Bundle")
    button.click().run()
    repros = list((tmp_path / "repros").glob("repro_*.zip"))
    assert repros
