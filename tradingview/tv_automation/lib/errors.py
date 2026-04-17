"""Typed error taxonomy for TV automation.

Every CLI maps these to specific exit codes so callers (shell, Claude,
schedulers) can branch on *why* something failed instead of just "non-zero."
"""

from __future__ import annotations


class TVAutomationError(Exception):
    """Base for all TV automation errors."""
    exit_code: int = 1


class NotLoggedInError(TVAutomationError):
    """No TradingView session cookie. User must sign in to the Chromium
    Automation profile. Everything else is downstream of this."""
    exit_code = 2


class NotPaperTradingError(TVAutomationError):
    """Trading Panel's active broker is not Paper Trading. Refuse to
    place/cancel/close any order — clicking could hit a real broker.
    This is the single most important guard in the system."""
    exit_code = 3

    def __init__(self, broker_label: str | None):
        self.broker_label = broker_label
        super().__init__(
            f"Active broker is {broker_label!r}, not Paper Trading. "
            "Refusing to interact with order controls."
        )


class SelectorDriftError(TVAutomationError):
    """A critical named selector didn't resolve against the DOM within
    the timeout. Means TradingView shipped a UI change and we need to
    re-probe. Raised instead of silently clicking the wrong element."""
    exit_code = 4

    def __init__(self, name: str, surface: str, candidates: list[str]):
        self.name = name
        self.surface = surface
        self.candidates = candidates
        super().__init__(
            f"Selector {surface}.{name!r} did not resolve. "
            f"Candidates tried: {candidates}. "
            f"Re-run the probe for surface {surface!r}."
        )


class ModalError(TVAutomationError):
    """An expected modal dialog did not appear, or one appeared that
    we didn't expect. Either case means the UI is in an unexpected state."""
    exit_code = 5


class VerificationFailedError(TVAutomationError):
    """An action appeared to succeed (no click error, no timeout) but
    the post-action state check didn't match expectations. E.g. we
    typed qty=5 but the qtyEl reads '1'. Never retry blindly on this."""
    exit_code = 6

    def __init__(self, what: str, expected, actual):
        self.what = what
        self.expected = expected
        self.actual = actual
        super().__init__(f"{what}: expected {expected!r}, got {actual!r}")


class LimitViolationError(TVAutomationError):
    """Request exceeds a configured safety limit (symbol allowlist,
    max qty, etc.). Defense-in-depth against an LLM hallucination."""
    exit_code = 7


class ChartNotReadyError(TVAutomationError):
    """Chart page didn't reach usable state (canvas visible, quick-trade
    bar hydrated) within the timeout. Often means the page is on a
    non-chart URL or TradingView is having issues."""
    exit_code = 8
