"""
Streamlit entry wrapper for Gigatrader.
- Detects the real UI script (ui/app.py, ui/main.py, ui/index.py, streamlit_app.py, app.py, main.py, index.py)
- Executes it in __main__ so Streamlit behaves as if that file was run directly.
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repo root
UI = ROOT / "ui"

# Make repo imports work in Streamlit subprocess
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Candidate order (customize if you add a preferred file)
CANDIDATES = [
    UI / "app.py",
    UI / "main.py",
    UI / "index.py",
    ROOT / "streamlit_app.py",
    ROOT / "app.py",
    ROOT / "main.py",
    ROOT / "index.py",
]

target = None
for cand in CANDIDATES:
    if cand.exists():
        target = cand
        break

if target is None:
    # Last-chance: any *.py under ui/ that mentions "streamlit"
    try:
        for p in UI.rglob("*.py"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore").lower()
                if "import streamlit" in text or "st.set_page_config" in text:
                    target = p
                    break
            except Exception:
                pass
    except Exception:
        pass

if target is None:
    import streamlit as st
    st.error("No Streamlit entry found.\nLooked for: ui/app.py, ui/main.py, ui/index.py, streamlit_app.py, app.py, main.py, index.py")
else:
    # Show which file we’re using, then execute it as the main script
    print(f"[UI] Using entry: {target.relative_to(ROOT)}")
    runpy.run_path(str(target), run_name="__main__")
