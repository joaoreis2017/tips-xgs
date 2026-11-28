"""BrowserSession's proxy wiring -- see config.AppConfig.betclic_proxy.

Real bug report (2026-10-02): Betclic geo-blocks GitHub Actions'
datacenter IP (confirmed via browser.py's own diagnostic logging --
an "Error 403 Forbidden" page). The fix routes the Betclic session
through a proxy via Playwright's own ``proxy`` launch option -- these
tests only check that BrowserSession actually passes it through
(and passes ``None`` through unchanged when no proxy is configured),
not real browser/network behavior.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from tipsxgs.browser import BrowserSession


@pytest.fixture
def fake_playwright(monkeypatch):
    """Stub out playwright.sync_api.sync_playwright so __enter__ never
    touches a real browser -- just records what chromium.launch() was
    called with."""
    mock_browser = MagicMock()
    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser
    mock_playwright_instance = MagicMock()
    mock_playwright_instance.chromium = mock_chromium
    mock_sync_playwright = MagicMock()
    mock_sync_playwright.return_value.start.return_value = mock_playwright_instance

    # _goto imports TimeoutError from this same module to catch a slow
    # navigation -- the fake module needs SOME exception class there,
    # even though no test here actually raises it.
    fake_module = types.SimpleNamespace(sync_playwright=mock_sync_playwright, TimeoutError=TimeoutError)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    return mock_chromium


def test_browser_session_passes_proxy_through_to_chromium_launch(fake_playwright):
    proxy = {"server": "http://pt-proxy.example.com:8080", "username": "u", "password": "p"}
    session = BrowserSession(proxy=proxy)
    session.__enter__()

    fake_playwright.launch.assert_called_once_with(headless=True, proxy=proxy)


def test_browser_session_defaults_to_no_proxy(fake_playwright):
    session = BrowserSession()
    session.__enter__()

    fake_playwright.launch.assert_called_once_with(headless=True, proxy=None)


# --- get_html_and_captured_json's click_selector (2026-11-19) -----------
#
# Real case: a page whose "current tab" was assumed stable (xgscore.
# results' "Yesterday" default) silently changed, and nothing checked
# WHICH tab was showing -- only that some JSON came back. click_selector
# lets a caller click a specific tab/button before reading the page
# instead of trusting its current default.


@pytest.fixture
def fake_page(fake_playwright):
    """A BrowserSession whose context.new_page() returns a MagicMock page
    (goto/wait_for_timeout/click/content/evaluate all no-ops), so
    get_html_and_captured_json can run without a real browser."""
    session = BrowserSession()
    session.__enter__()
    mock_page = MagicMock()
    mock_page.content.return_value = "<html></html>"
    session._context = MagicMock()
    session._context.new_page.return_value = mock_page
    return session, mock_page


def test_get_html_and_captured_json_clicks_the_given_selector(fake_page):
    session, mock_page = fake_page
    session.get_html_and_captured_json("https://example.com", click_selector=".yesterday-tab", click_wait_ms=999)

    mock_page.click.assert_called_once_with(".yesterday-tab")
    # The extra wait happens AFTER the click, not instead of it.
    assert mock_page.wait_for_timeout.call_args_list[-1].args == (999,)


def test_get_html_and_captured_json_never_clicks_without_a_selector(fake_page):
    session, mock_page = fake_page
    session.get_html_and_captured_json("https://example.com")

    mock_page.click.assert_not_called()
