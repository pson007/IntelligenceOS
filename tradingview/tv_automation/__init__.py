"""TradingView browser automation.

Drives the automation-profile Chromium (attached via CDP) to perform any
action a user could do in the TradingView UI: chart control, indicators,
Pine Editor, strategy backtesting, paper trades, and more.

Run modules as CLIs (from any working directory — see below):

    python -m tv_automation.trading place-order NVDA buy 1
    python -m tv_automation.trading positions
    python -m tv_automation.chart set-symbol AAPL --tf 1D
    python -m tv_automation.pine_editor apply path/to/file.pine
    python -m tv_automation.strategy_tester metrics

Precondition: Chromium-Automation profile is running with CDP on
localhost:9222 (start_chrome_cdp.sh handles this) and the user is
signed into TradingView in that profile. That's the only manual step.
"""

# ---------------------------------------------------------------------------
# CWD independence: session.py and preflight.py live at tradingview/
# (one level up from this package). Normally `python -m tv_automation.X`
# only puts the current working directory on sys.path, so these imports
# break if the caller runs the CLI from anywhere other than tradingview/.
# We proactively insert the parent directory here so every module in the
# package can `from session import ...` regardless of CWD.
# ---------------------------------------------------------------------------

import sys as _sys
from pathlib import Path as _Path

_PARENT = str(_Path(__file__).resolve().parent.parent)
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)
