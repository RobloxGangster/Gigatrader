import os, pytest

UI = f"http://127.0.0.1:{os.getenv('GT_UI_PORT','8501')}"


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_control_center(page):
    page.goto(UI, timeout=60000)
    page.wait_for_selector("text=Gigatrader", timeout=30000)

    # Sidebar dropdown labelled "Navigation" exists (new nav)
    page.get_by_label("Navigation").click()
    page.get_by_role("option", name="Control Center", exact=False).click()
    page.wait_for_selector("text=Control Center", timeout=30000)


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_nav_to_diagnostics_and_run(page):
    page.goto(UI, timeout=60000)
    page.get_by_label("Navigation").click()
    # Some repos label it "Diagnostics / Logs", fallback to "Logs"
    if page.get_by_role("option", name="Diagnostics / Logs", exact=False).is_visible():
        page.get_by_role("option", name="Diagnostics / Logs", exact=False).click()
    else:
        page.get_by_role("option", name="Logs", exact=False).click()

    page.wait_for_selector("text=Diagnostics", timeout=30000)
    # Run diagnostics button
    page.get_by_role("button", name="Run UI Diagnostics", exact=False).click()
    # Expect a success or results area to appear
    page.wait_for_selector("text=checks —", timeout=30000)  # success banner contains 'checks —'
