"""Streamlit entrypoint delegating to :mod:`ui.Home` navigation shell."""

from __future__ import annotations

from ui.Home import main as _run_main


def main() -> None:
    """Render the Gigatrader UI using the consolidated Home router."""

    _run_main()


if __name__ == "__main__":
    main()
