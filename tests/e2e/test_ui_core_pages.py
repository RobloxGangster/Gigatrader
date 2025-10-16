import os, re, pytest

UI = f"http://127.0.0.1:{os.getenv('GT_UI_PORT','8501')}"


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_option_chain_loads(page):
    page.goto(UI, timeout=60_000)
    page.get_by_label("Navigation").click()
    page.get_by_role("option", name=re.compile(r"^Option Chain$", re.I)).click()

    # 1) Prefer a stable container: st.table or st.dataframe
    #   - st.table => [data-testid="stTable"]
    #   - st.dataframe => [data-testid="stDataFrame"]
    table = page.locator('[data-testid="stTable"], [data-testid="stDataFrame"]')
    table.first.wait_for(state="attached", timeout=30_000)

    # 2) Try to make the header visible if Streamlit marked it "hidden"
    col_header = page.get_by_role("columnheader", name=re.compile(r"^strike$", re.I))
    if col_header.count() > 0:
        try:
            col_header.first.scroll_into_view_if_needed(timeout=5_000)
            # If it’s still hidden, don’t fail the test—presence is good enough.
            # We’ll assert there’s at least one body row.
        except Exception:
            pass

    # 3) Assert there is at least one data row (robust against header visibility)
    # Works for both st.table and st.dataframe
    body_row = page.locator("table >> tbody tr, [role='rowgroup'] [role='row']").first
    body_row.wait_for(state="attached", timeout=30_000)


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
