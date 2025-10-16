import pytest
from playwright.sync_api import Page

from ._nav import goto_page, wait_for_heading


@pytest.mark.e2e
@pytest.mark.usefixtures("server_stack")
def test_option_chain_loads(page: Page):
    goto_page(page, "Option Chain")
    wait_for_heading(page, ("Option Chain",))
