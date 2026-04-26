"""Exception types raised by the Lucy runtime core."""

from __future__ import annotations


class LucyError(Exception):
    """Base error for Lucy runtime failures."""


class ToolExecutionError(LucyError):
    """A registered tool raised or returned an error during execution."""


class ResponsesAPIError(LucyError):
    """A Foundry/OpenAI Responses API call failed."""


class SessionStateError(LucyError):
    """Session state is missing required fields for the requested operation."""
