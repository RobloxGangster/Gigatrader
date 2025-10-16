import os, pytest

UI = f"http://127.0.0.1:{os.getenv('GT_UI_PORT','8501')}"


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_option_chain_loads(page):
    page.goto(UI, timeout=60000)
    page.get_by_label("Navigation").click()
    page.get_by_role("option", name="Option Chain", exact=False).click()
    # At least column header should be visible
    page.wait_for_selector("text=Strike", timeout=30000)


@pytest.mark.e2e
@pytest.mark.paper_only
@pytest.mark.usefixtures("server_stack")
def test_control_center_kpis_in_paper(page, require_paper):
    page.goto(UI, timeout=60000)
    page.get_by_label("Navigation").click()
    page.get_by_role("option", name="Control Center", exact=False).click()
    page.wait_for_selector("text=Portfolio Value", timeout=30000)
    page.wait_for_selector("text=Buying Power", timeout=30000)
    # Try Sync Now if present
    if page.get_by_role("button", name="Sync Now", exact=False).is_visible():
        page.get_by_role("button", name="Sync Now", exact=False).click()
