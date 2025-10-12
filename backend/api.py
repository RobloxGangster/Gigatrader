import os, asyncio, threading
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(override=False)
app = FastAPI(title="Gigatrader API")

# Runner lifecycle
_runner_thread: threading.Thread | None = None
_runner_stop: asyncio.Event | None = None
_running = False
_profile = "paper"
_KILL_FILE = Path(os.getenv("KILL_SWITCH_FILE", ".kill_switch"))


class StartReq(BaseModel):
    preset: str | None = None


def _clear_kill_switch() -> None:
    try:
        _KILL_FILE.unlink()
    except FileNotFoundError:
        pass


def _engage_kill_switch() -> None:
    try:
        _KILL_FILE.touch()
    except OSError:
        pass


def _run_runner() -> None:
    global _running
    try:
        from services.runtime import runner as R
        R.main()
    finally:
        _running = False
        if _runner_stop is not None:
            _runner_stop.set()


@app.get("/status")
def status():
    return {
        "running": _running,
        "profile": _profile,
        "paper": os.getenv("TRADING_MODE", "paper") == "paper",
        "halted": bool(os.getenv("KILL_SWITCH", "").lower() in ("1", "true", "yes"))
        or _KILL_FILE.exists(),
    }


@app.post("/paper/start")
def paper_start(req: StartReq | None = None):
    del req
    global _runner_thread, _running, _profile, _runner_stop
    if _running:
        return {"run_id": "active"}
    _clear_kill_switch()
    os.environ["TRADING_MODE"] = "paper"
    os.environ["ALPACA_PAPER"] = "true"
    _profile = "paper"
    _running = True
    _runner_stop = asyncio.Event()
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id": "paper"}


@app.post("/paper/stop")
def paper_stop():
    global _running
    _running = False
    _engage_kill_switch()
    if _runner_stop is not None:
        _runner_stop.set()
    return {"ok": True}


@app.post("/paper/flatten")
def flatten_and_halt():
    _engage_kill_switch()
    return {"ok": True, "halted": True}


# Live endpoints guarded by env
@app.post("/live/start")
def live_start(req: StartReq | None = None):
    del req
    if os.getenv("LIVE_TRADING", "false").lower() not in ("1", "true", "yes"):
        raise HTTPException(403, "LIVE_TRADING env not enabled")
    global _runner_thread, _running, _profile, _runner_stop
    if _running:
        return {"run_id": "active"}
    _clear_kill_switch()
    os.environ["TRADING_MODE"] = "live"
    os.environ["ALPACA_PAPER"] = "false"
    _profile = "live"
    _running = True
    _runner_stop = asyncio.Event()
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id": "live"}


def main() -> None:
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", "8000"))
    uvicorn.run("backend.api:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":  # pragma: no cover - manual entry point
    main()
