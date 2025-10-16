import os, re, pytest

from ._nav import open_nav_and_select

UI = f"http://127.0.0.1:{os.getenv('GT_UI_PORT','8501')}"


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page):
    page.goto(UI, timeout=60_000)
    page.wait_for_selector("text=Gigatrader", timeout=30_000)
    open_nav_and_select(page, r"^Control Center$")
    page.wait_for_selector("text=CONTROL_CENTER_READY", timeout=30_000)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page):
    page.goto(UI, timeout=60_000)
    open_nav_and_select(page, r"^(Diagnostics / Logs|Logs)$")
    page.wait_for_selector("text=DIAGNOSTICS_READY", timeout=30_000)

    page.get_by_role("button", name=re.compile(r"Run UI Diagnostics", re.I)).click()
    page.wait_for_selector(
        re.compile(r"(Ran\s+\d+\s+checks|Recent Diagnostic Runs|Details|PASS|SKIP)", re.I),
        timeout=45_000,
    )
