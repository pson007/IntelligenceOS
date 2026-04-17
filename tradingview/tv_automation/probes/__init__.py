"""Probe scripts — map surfaces of the TradingView UI to stable selectors.

When TradingView ships a UI change and a selector drifts, re-run the
probe for that surface. Each probe:

  1. Navigates to the relevant UI state (opens a panel, clicks a button).
  2. Dumps every [data-name] / [aria-label] / button / input inside the
     surface to a JSON file under tv_automation/probes/snapshots/.
  3. Prints the selectors most likely to be the canonical ones for each
     role, so you can copy them into selectors.yaml.

Run via `.venv/bin/python -m tv_automation.probes.probe_<surface>`.
"""
