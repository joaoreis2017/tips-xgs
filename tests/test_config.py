"""AppConfig.betclic_proxy -- see config.py's own comment above the three
betclic_proxy_* fields for the real bug report (Betclic geo-blocking
GitHub Actions) this exists to work around.
"""

from __future__ import annotations

from tipsxgs.config import AppConfig, load_config


def test_betclic_proxy_is_none_when_server_not_set(monkeypatch):
    monkeypatch.delenv("BETCLIC_PROXY_SERVER", raising=False)
    monkeypatch.delenv("BETCLIC_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("BETCLIC_PROXY_PASSWORD", raising=False)

    cfg = load_config()
    assert cfg.betclic_proxy_server is None
    assert cfg.betclic_proxy is None


def test_betclic_proxy_read_from_environment_not_from_yaml(monkeypatch):
    # Deliberately NEVER read from config.yaml -- a proxy's credentials
    # are secrets, and config.yaml is version-controlled.
    monkeypatch.setenv("BETCLIC_PROXY_SERVER", "http://pt-proxy.example.com:8080")
    monkeypatch.setenv("BETCLIC_PROXY_USERNAME", "someuser")
    monkeypatch.setenv("BETCLIC_PROXY_PASSWORD", "somepass")

    cfg = load_config()
    assert cfg.betclic_proxy == {
        "server": "http://pt-proxy.example.com:8080",
        "username": "someuser",
        "password": "somepass",
    }


def test_betclic_proxy_omits_username_and_password_when_unset():
    cfg = AppConfig(
        timezone="Europe/Lisbon",
        data_dir="data",
        reports_dir="data",
        value_bet_threshold=1.0,
        min_match_confidence=80.0,
        max_concurrent_previews=3,
        headless=True,
        user_agent="x",
        xgscore=None,
        betclic=None,
        betclic_proxy_server="http://pt-proxy.example.com:8080",
    )
    assert cfg.betclic_proxy == {"server": "http://pt-proxy.example.com:8080"}
