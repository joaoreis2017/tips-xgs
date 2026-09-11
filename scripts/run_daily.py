#!/usr/bin/env python3
"""Thin wrapper for cron/systemd: `python scripts/run_daily.py`.

Equivalent to `python -m tipsxgs run`, kept as a standalone script so a
crontab entry doesn't need to know about `-m` module invocation or the
package's installed location.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tipsxgs.cli import cli  # noqa: E402

if __name__ == "__main__":
    cli(["run", *sys.argv[1:]])
