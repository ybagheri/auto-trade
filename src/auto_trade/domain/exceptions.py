from __future__ import annotations


class AutoTradeError(Exception):
    """Base exception for the application."""


class InvalidSignalError(AutoTradeError):
    """Raised when a signal cannot be parsed or normalized."""


class SafetyViolation(AutoTradeError):
    """Raised when an execution safety gate rejects a request."""


class TerminalNotFoundError(AutoTradeError):
    """Raised when the configured terminal cannot be identified."""


class AutomationError(AutoTradeError):
    """Raised when the desktop automation adapter cannot complete an action."""


class ExecutionUnknownError(AutoTradeError):
    """Raised when execution cannot be proven or disproven."""
