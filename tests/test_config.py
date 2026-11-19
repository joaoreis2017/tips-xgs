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


def test_real_rate_page_bands_default_to_the_backtested_middle_ground(tmp_path):
    # Explicitly requested (2026-11-18), after backtesting 5 days of
    # accumulated history: the "apostas por taxa real" page's own
    # defaults (separate from the model-probability page's
    # report_mid_*/report_high_* fields, which this must NOT touch).
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("xgscore: {}\nbetclic: {}\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.report_real_multiple_leg_cap == 3
    assert cfg.report_real_mid_probability_min == 0.60
    assert cfg.report_real_mid_odd_min == 1.8
    assert cfg.report_real_mid_odd_max == 2.5
    # Unchanged, model-probability page fields.
    assert cfg.report_mid_probability_min == 0.70
    assert cfg.report_mid_odd_min == 1.5
    assert cfg.report_mid_odd_max == 2.2


def test_real_rate_page_bands_are_overridable_from_config_yaml(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "xgscore: {}\nbetclic: {}\n"
        "report_real_multiple_leg_cap: 4\n"
        "report_real_mid_probability_min: 0.55\n"
        "report_real_mid_odd_min: 1.9\n"
        "report_real_mid_odd_max: 2.6\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.report_real_multiple_leg_cap == 4
    assert cfg.report_real_mid_probability_min == 0.55
    assert cfg.report_real_mid_odd_min == 1.9
    assert cfg.report_real_mid_odd_max == 2.6


def test_real_rate_page_leg_cap_can_be_disabled_with_null(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("xgscore: {}\nbetclic: {}\nreport_real_multiple_leg_cap: null\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.report_real_multiple_leg_cap is None


def test_page_config_click_selector_defaults_to_none(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("xgscore: {results: {}}\nbetclic: {}\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.xgscore.page("results").click_selector is None
    assert cfg.xgscore.page("results").click_wait_ms == 1500


def test_page_config_click_selector_is_read_from_config_yaml(tmp_path):
    # Explicitly requested (2026-11-19), after a real case: xgscore.
    # results' own "Yesterday" tab default silently changed to "Today"
    # with no error -- click_selector lets a page explicitly click a
    # tab/button before reading it instead of trusting the default.
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "xgscore: {results: {click_selector: 'button.yesterday', click_wait_ms: 2500}}\nbetclic: {}\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.xgscore.page("results").click_selector == "button.yesterday"
    assert cfg.xgscore.page("results").click_wait_ms == 2500


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
