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

    fake_module = types.SimpleNamespace(sync_playwright=mock_sync_playwright)
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
