from importlib import reload
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.services import config


def test_api_base_url_default(monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    module = reload(config)
    module.reset_api_base_url_cache()
    assert module.api_base_url() == "http://127.0.0.1:8000"


def test_api_base_url_override(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://example.com/api/")
    module = reload(config)
    module.reset_api_base_url_cache()
    assert module.api_base_url() == "https://example.com/api"


def test_mock_mode_flag(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "false")
    module = reload(config)
    assert module.mock_mode() is False
    monkeypatch.setenv("MOCK_MODE", "true")
    module = reload(config)
    assert module.mock_mode() is True
