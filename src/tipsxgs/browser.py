"""Thin Playwright wrapper used by every scraper.

Both xGScore and Betclic render their data client-side (SPA-style), so a
plain ``requests.get`` typically returns an near-empty HTML shell. We use a
real (headless) browser instead and wait for network activity to settle
before reading the DOM.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)


class BrowserSession:
    """A single reusable headless-browser context.

    Usage::

        with BrowserSession(headless=True) as session:
            html = session.get_html("https://xgscore.io/")
            data = session.get_html_and_json("https://xgscore.io/.../preview")
    """

    def __init__(self, headless: bool = True, user_agent: str | None = None, timeout_ms: int = 30_000):
        self.headless = headless
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(user_agent=self.user_agent)
        self._context.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *exc):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    @contextmanager
    def _page(self):
        page = self._context.new_page()
        try:
            yield page
        finally:
            page.close()

    def get_html(self, url: str, wait_selector: str | None = None, wait_ms: int = 1500) -> str:
        """Navigate to ``url`` and return the fully rendered HTML.

        ``wait_selector``, if given, is awaited before reading the DOM
        (use this once you know a real, stable selector for the page's
        main content -- see docs/CALIBRATION.md). Otherwise we just give
        the SPA ``wait_ms`` to finish its initial render after the DOM is
        ready.

        We wait for ``"domcontentloaded"`` rather than ``"networkidle"``:
        pages with live/polling data (odds, scores) or websockets --
        Betclic especially -- never go network-idle, so waiting for that
        just times out. If even ``domcontentloaded`` doesn't fire in time
        (slow site, redirect chain) we log it and fall back to whatever
        rendered so far instead of raising.
        """
        with self._page() as page:
            self._goto(page, url)
            if wait_selector:
                page.wait_for_selector(wait_selector)
            else:
                page.wait_for_timeout(wait_ms)
            return page.content()

    def _goto(self, page, url: str) -> None:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        try:
            page.goto(url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            logger.warning(
                "Timed out waiting for %s to finish loading -- continuing with "
                "whatever rendered so far (the page may be incomplete).",
                url,
            )

    def get_html_and_captured_json(
        self, url: str, url_substring_filter: str | None = None, wait_ms: int = 2000
    ) -> tuple[str, list[dict]]:
        """Navigate to ``url``, capture any JSON XHR/fetch responses, and
        return ``(html, [decoded_json_bodies])``.

        Many sports-data SPAs fetch their prediction/odds payload from a
        dedicated JSON API rather than (or in addition to) embedding it in
        the HTML. ``url_substring_filter`` narrows capture to responses
        whose URL contains that substring (e.g. "api" or "predictions") --
        leave it unset to capture every JSON response, which is a good
        first step when calibrating (see scripts/inspect_site.py).
        """
        captured: list[dict] = []

        def _on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                if url_substring_filter and url_substring_filter not in response.url:
                    return
                captured.append(response.json())
            except Exception:  # noqa: BLE001 - best-effort capture
                logger.debug("could not decode JSON response from %s", response.url, exc_info=True)

        with self._page() as page:
            page.on("response", _on_response)
            self._goto(page, url)
            page.wait_for_timeout(wait_ms)
            html = page.content()
        return html, captured


@contextmanager
def polite_delay(seconds: float) -> Iterator[None]:
    """Context manager that sleeps ``seconds`` on exit -- use between
    requests to the same host to avoid hammering it."""
    try:
        yield
    finally:
        time.sleep(max(0.0, seconds))
