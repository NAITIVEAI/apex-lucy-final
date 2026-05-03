"""Production runtime factory shared by non-Chainlit adapters."""

from __future__ import annotations

import logging

from .runtime import LucyRuntime

logger = logging.getLogger(__name__)


async def default_runtime_factory() -> LucyRuntime:
    """Construct LucyRuntime from apex.py's initialized Foundry globals.

    This intentionally preserves the current locked production tool registry.
    apex.py still owns some Chainlit-coupled helper registration, so non-Chainlit
    adapters import apex until those tools are extracted into a fully portable
    module.
    """
    import apex

    await apex._initialize_persistent_agent_v2()
    if not (apex.openai_client and apex.agent_name and apex.agent_version):
        raise RuntimeError(
            "apex._initialize_persistent_agent_v2() returned but globals are "
            "not set. Cannot construct LucyRuntime."
        )
    logger.info(
        "LucyRuntime bound to apex globals: agent=%s version=%s tools=%d",
        apex.agent_name,
        apex.agent_version,
        len(apex.v2_function_registry or {}),
    )
    runtime = LucyRuntime(
        openai_client=apex.openai_client,
        agent_name=apex.agent_name,
        agent_version=apex.agent_version,
        function_registry=apex.v2_function_registry,
    )
    runtime.project_client = apex.project_client
    return runtime
