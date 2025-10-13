import os, threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from core.kill_switch import is_active
load_dotenv(override=False)

app = FastAPI(title="Gigatrader API")


@app.get("/health")
def health():
    return {"ok": True, "service": "gigatrader-api"}
_runner_thread = None
_running = False
_profile = "paper"


class StartReq(BaseModel):
    preset: str | None = None


def _run_runner():
    global _running
    try:
        from services.runtime import runner as R
        R.main()
    finally:
        _running = False


@app.get("/status")
def status():
    return {
        "running": _running,
        "profile": _profile,
        "paper": os.getenv("TRADING_MODE","paper")=="paper",
        "halted": is_active(),
    }


@app.post("/paper/start")
def paper_start(req: StartReq | None = None):
    global _runner_thread, _running, _profile
    if _running: return {"run_id":"active"}
    os.environ["TRADING_MODE"]="paper"
    os.environ["ALPACA_PAPER"]="true"
    _profile = "paper"
    _running = True
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id":"paper"}


@app.post("/paper/stop")
def paper_stop():
    global _running
    _running = False
    open(".kill_switch","w").close()
    return {"ok": True}


@app.post("/paper/flatten")
def flatten_and_halt():
    open(".kill_switch","w").close()
    return {"ok": True, "halted": True}


@app.post("/live/start")
def live_start(req: StartReq | None = None):
    if os.getenv("LIVE_TRADING","false").lower() not in ("1","true","yes"):
        raise HTTPException(403,"LIVE_TRADING env not enabled")
    global _runner_thread, _running, _profile
    if _running: return {"run_id":"active"}
    os.environ["TRADING_MODE"]="live"
    os.environ["ALPACA_PAPER"]="false"
    _profile = "live"
    _running = True
    _runner_thread = threading.Thread(target=_run_runner, daemon=True)
    _runner_thread.start()
    return {"run_id":"live"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", "8000"))
    print(f"\n=== Gigatrader API starting on 127.0.0.1:{port} ===")
    uvicorn.run("backend.api:app", host="127.0.0.1", port=port, reload=False)
