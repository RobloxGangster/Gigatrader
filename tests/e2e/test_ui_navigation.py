import os, pytest
from ._nav import open_nav_and_select_exact

UI = f"http://127.0.0.1:{os.getenv('GT_UI_PORT','8501')}"


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page):
    page.goto(UI, timeout=60_000)
    page.wait_for_selector("text=Gigatrader", timeout=30_000)
    open_nav_and_select_exact(page, "Control Center")
    # Prefer anchor, fallback to KPIs if anchor missing
    try:
        page.wait_for_selector("text=CONTROL_CENTER_READY", timeout=15_000)
    except Exception:
        page.wait_for_selector("text=Portfolio Value, text=Buying Power, text=Risk Overview", timeout=30_000)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page):
    page.goto(UI, timeout=60_000)
    open_nav_and_select_exact(page, "Diagnostics / Logs", "Logs")
    # Prefer anchor, fallback to button/header
    try:
        page.wait_for_selector("text=DIAGNOSTICS_READY", timeout=15_000)
    except Exception:
        page.wait_for_selector("text=Run UI Diagnostics, text=Diagnostics", timeout=30_000)
    page.get_by_role("button", name="Run UI Diagnostics").click()
    page.wait_for_selector("text=Recent Diagnostic Runs, text=Details, text=checks —", timeout=45_000)
