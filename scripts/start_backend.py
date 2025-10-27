"""
Spawn the FastAPI backend (uvicorn backend.api:app) on 127.0.0.1:8000.

This script is launched by the Streamlit UI via subprocess.Popen.
It runs uvicorn in THIS process and writes logs to logs/backend_autostart.log
so the UI can show you what went wrong if startup fails.

IMPORTANT: This process blocks forever. Do not call it in-process.
"""

import os
import uvicorn

LOG_DIR = os.path.join("logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "backend_autostart.log")

def main() -> None:
    # load .env so Alpaca keys etc. are available here
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass

    # redirect uvicorn logging into a file we can inspect
    # we'll run uvicorn programmatically; uvicorn itself will still write to stderr,
    # but we let Streamlit spawn us detatched, so that's fine.
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write("\n=== START backend_autostart ===\n")

    uvicorn.run(
        "backend.api:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=False,
    )

if __name__ == "__main__":
    main()
