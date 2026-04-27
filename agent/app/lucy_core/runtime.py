"""LucyRuntime — UI-independent orchestrator.

Bridges adapters (Chainlit, FastAPI HTTP wrapper, evals) to the Responses-API
loop in `lucy_core.responses_loop`. Accepts pre-initialized Foundry/OpenAI
clients and a function registry as constructor parameters.

Note on initialization scope (intentionally limited):
The Foundry agent publication / version reconciliation / client construction
flow currently lives in `agent/app/apex.py:_initialize_persistent_agent_v2`
and populates module-level globals. Extracting that into the runtime is a
larger, riskier task and is deferred. For now, the caller initializes those
globals before constructing a LucyRuntime.
"""

from __future__ import annotations

import logging
from typing import Any

from .artifacts import extract_artifacts_from_tool_outputs
from .handoff import extract_handoff_from_tool_outputs, handoff_artifact_from_payload
from .responses_loop import run_response_v2
from .session import LucyRequest, LucyResponse

logger = logging.getLogger(__name__)


class LucyRuntime:
    """Adapter-independent runtime for Lucy.

    Construct with already-initialized Foundry/OpenAI dependencies, then call
    `respond(LucyRequest) -> LucyResponse` from any adapter.
    """

    def __init__(
        self,
        openai_client: Any,
        agent_name: str,
        agent_version: str,
        function_registry: dict[str, Any],
    ) -> None:
        self.openai_client = openai_client
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.function_registry = function_registry

    async def respond(self, request: LucyRequest) -> LucyResponse:
        """Run one turn of the Responses-API loop and return a structured response.

        `request.session` is mutated in place — conversation_id,
        previous_response_id, and last_eval_final_response_id may all be
        updated by the loop. Adapters are responsible for persisting those
        updates back to their session store.
        """
        result = await run_response_v2(
            user_text=request.input_text,
            session=request.session,
            openai_client=self.openai_client,
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            function_registry=self.function_registry,
        )
        artifacts = extract_artifacts_from_tool_outputs(
            result.get("tool_outputs", []),
            assistant_text=result.get("text"),
        )
        handoff = extract_handoff_from_tool_outputs(
            result.get("tool_outputs", []),
            assistant_text=result.get("text"),
            reason=request.metadata.get("handoff_reason"),
        )
        if handoff is not None:
            handoff_artifact = handoff_artifact_from_payload(handoff)
            if handoff_artifact is not None:
                artifacts.append(handoff_artifact)
        return LucyResponse(
            text=result["text"],
            session=request.session,
            tool_calls=result.get("tool_outputs", []),
            artifacts=artifacts,
            handoff=handoff,
        )
