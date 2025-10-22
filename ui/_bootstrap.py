from __future__ import annotations

import os
import sys
from pathlib import Path

# Repository root (…/Gigatrader)
ROOT = Path(__file__).resolve().parents[1]

# Ensure the repo root is on sys.path so `import ui.*` works even when
# Streamlit’s CWD isn’t the project root.
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

# Also help child processes/tests that inherit PYTHONPATH
os.environ.setdefault("PYTHONPATH", root_str + os.pathsep + os.environ.get("PYTHONPATH", ""))
