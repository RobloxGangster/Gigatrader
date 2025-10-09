# Gigatrader UI

Streamlit dashboard for controlling and observing the Gigatrader automated equities and options trading platform.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # ensure streamlit, plotly, pydantic
cp .env.example .env
make ui-dev
```

## Testing

```bash
make ui-test
```

## Mock mode

The UI defaults to mock mode (`MOCK_MODE=true`). A banner in the sidebar confirms when mock data is being used. Fixtures live in `ui/fixtures` and power deterministic responses.

## Screenshots

_Add screenshots of each page here._

## Keyboard shortcuts

* `g` then `b` → Backtests
* `g` then `l` → Logs
* `.` → Tail logs

