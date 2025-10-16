import os, pytest
from ._nav import open_nav_and_select_exact

UI = f"http://127.0.0.1:{os.getenv('GT_UI_PORT','8501')}"


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page):
    page.goto(UI, timeout=60_000)
    page.wait_for_selector("text=Gigatrader", timeout=30_000)
    open_nav_and_select_exact(page, "Control Center")
    page.wait_for_selector("text=CONTROL_CENTER_READY", timeout=30_000)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page):
    page.goto(UI, timeout=60_000)
    open_nav_and_select_exact(page, "Diagnostics / Logs", "Logs")  # exact text first; safe fallback second
    page.wait_for_selector("text=DIAGNOSTICS_READY", timeout=30_000)

    # Run diagnostics (keep tolerant)
    page.get_by_role("button", name="Run UI Diagnostics").click()
    page.wait_for_selector("text=Recent Diagnostic Runs, text=Details, text=checks —", timeout=45_000)
