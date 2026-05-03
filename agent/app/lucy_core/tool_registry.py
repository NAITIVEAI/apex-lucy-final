"""Tool registry construction for the Lucy runtime core.

Assembles the canonical Lucy tool list, builds a name->callable registry for
invocation, and computes a stable signature of the toolset for detecting
changes between agent versions. UI-independent: callable dependencies are
injected as parameters so these helpers can run under Chainlit, FastAPI, or
direct programmatic invocation.

Behavior mirrors the pre-extraction implementations in agent/app/apex.py:
_build_lucy_function_list, _build_function_registry, _toolset_signature.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def build_lucy_function_list(
    setup_dynamics_fn: Callable[[], list[Any]] | None,
    core_helpers: list[Callable[..., Any]],
    setup_handoff_fn: Callable[[], list[Any]] | None,
) -> list[Any]:
    """Assemble the canonical Lucy tool list.

    setup_dynamics_fn: returns Dynamics 365 tool callables, or None if unavailable.
    core_helpers: built-in helper tool callables (SAS, PDF, datetime, search, etc).
    setup_handoff_fn: returns handoff tool callables, or None if not loaded.
        Failures inside this callable are logged and swallowed to preserve the
        prior tolerance for missing handoff support.
    """
    functions: list[Any] = []

    if setup_dynamics_fn is None:
        logger.warning("⚠️ setup_dynamics_functions not available; no Dynamics tools registered")
    else:
        functions.extend(setup_dynamics_fn())

    functions.extend(core_helpers)

    if setup_handoff_fn is not None:
        try:
            functions.extend(setup_handoff_fn())
            logger.info("✅ Added handoff functions to v2 toolset")
        except Exception as handoff_error:
            logger.warning("⚠️ Could not add handoff functions: %s", handoff_error)

    return functions


def build_function_registry(functions: list[Any]) -> dict[str, Any]:
    """Build a name -> callable registry. Skips non-callables and unnamed items;
    logs a warning on duplicate names (last wins, matching prior behavior)."""
    registry: dict[str, Any] = {}
    for func in functions:
        if not callable(func):
            continue
        name = getattr(func, "__name__", None) or ""
        if not name:
            continue
        if name in registry:
            logger.warning("⚠️ Duplicate tool name detected: %s (overwriting)", name)
        registry[name] = func
    return registry


def toolset_signature(functions: list[Any]) -> str:
    """Stable SHA-256 hex digest of the toolset, computed from sorted callable names."""
    names: list[str] = []
    for func in functions:
        if not callable(func):
            continue
        name = getattr(func, "__name__", None)
        if name:
            names.append(name)
    joined = ",".join(sorted(names))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
