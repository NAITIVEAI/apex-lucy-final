"""Lucy runtime core — UI-independent agent orchestration.

Public surface:

- Data models: LucySession, LucyRequest, LucyResponse, LucyArtifact (session.py)
- Errors: LucyError, ToolExecutionError, ResponsesAPIError, SessionStateError (errors.py)
- Tool registry: build_lucy_function_list, build_function_registry, toolset_signature (tool_registry.py)
- Responses loop: run_response_v2, extract_v2_function_calls, execute_v2_tool_call, build_authenticated_state_items (responses_loop.py)
- Orchestrator: LucyRuntime (runtime.py)

The runtime is invoked from adapters that handle session marshalling and
output rendering: Chainlit (agent/app/apex.py), the FastAPI HTTP wrapper
for Foundry AI Gateway registration (planned), and Foundry evals.
"""

from .errors import (
    LucyError,
    ResponsesAPIError,
    SessionStateError,
    ToolExecutionError,
)
from .session import LucyArtifact, LucyRequest, LucyResponse, LucySession

__all__ = [
    "LucyArtifact",
    "LucyError",
    "LucyRequest",
    "LucyResponse",
    "LucyRuntime",
    "LucySession",
    "ResponsesAPIError",
    "SessionStateError",
    "ToolExecutionError",
]


def __getattr__(name: str):
    if name == "LucyRuntime":
        from .runtime import LucyRuntime

        return LucyRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
