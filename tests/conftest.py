import pathlib

import pytest


@pytest.fixture(scope="session", autouse=True)
def _clear_repo_killswitch_only():
    """
    Ensure a stray repo-root .kill_switch doesn't taint the suite,
    but DO NOT disable switch behavior globally (tests rely on tmp_path switches).
    """

    ks = pathlib.Path(".kill_switch")
    try:
        if ks.exists():
            ks.unlink()
    except Exception:
        pass
    yield
