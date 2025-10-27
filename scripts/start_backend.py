"""
Start the FastAPI backend (uvicorn backend.api:app) on 127.0.0.1:8000
and never return. This is meant to be spawned by Streamlit via subprocess.Popen.

On Windows this keeps the backend alive in its own process instead of relying
on a manually opened terminal.
"""

import os
import sys
import uvicorn

def main() -> None:
    # Ensure environment variables from .env are loaded if available
    # so Alpaca keys / PROFILE / DRY_RUN etc are present in this process.
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass

    # Run uvicorn directly in this process.
    uvicorn.run(
        "backend.api:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=False,          # reload=False because we're embedding in a subprocess
    )

if __name__ == "__main__":
    # Make sure we are running inside the venv python. We assume Control Center
    # calls us with that interpreter (`sys.executable` from inside Streamlit),
    # so we don't try to re-exec here. Just run.
    main()
