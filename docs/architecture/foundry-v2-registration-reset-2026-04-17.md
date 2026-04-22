# Foundry V2 Registration Reset Notes

**Date:** 2026-04-17  
**Scope:** Lucy self-hosted Chainlit runtime + Microsoft Foundry prompt-agent publication

## What We Learned

- Foundry now has two distinct layers that must not be conflated:
  - **Project agent versions** created by `create_version(...)`
  - **Agent Applications / Managed deployments** used by the Foundry portal and stable invocation surface
- The Azure Table `agentregistry` row is only a cache. It is **not** the source of truth for what the Foundry portal has actively routed.
- A project can accumulate multiple overlapping application lineages (`lucy`, `lucy-chat`, `lucy-chat-v2`) that look similar in the portal but are not interchangeable.
- The Responses runtime can fail with `404 not_found` if it tries to invoke an agent version that exists in deployment metadata but is not actually the active routed version the project endpoint can resolve.
- Foundry management APIs for application/deployment updates can return transient or opaque `SystemError` failures even when listing applications and deployments succeeds.

## Confirmed Azure Findings

- The legacy `lucy-chat-v2` application had multiple deployments (`1, 3, 5, 6, 7, 8`) while traffic still routed to version `1`.
- The runtime had previously drifted to a stale cached version (`8`), producing:
  - `Agent lucy-chat-v2 with version 8 not found`
- The clean reset path succeeded only after creating a **fresh canonical name**:
  - `agent-lucy-prod`
- The new `agent-lucy-prod` lineage was created and reconciled successfully:
  - application: `agent-lucy-prod`
  - deployment: `agent-lucy-prod`
  - version: `1`

## Runtime Rules Going Forward

- Treat the active routed application/deployment as the runtime authority for invocation.
- Treat the registry row as a convenience cache that must be reconciled against Azure on startup.
- Log stale-routing conditions loudly, but do not let a failed deployment-reroute call take Lucy down when a working active deployment already exists.
- Prefer a fresh canonical Foundry app name over trying to salvage polluted application lineages.

## Operational Guidance

- When Lucy appears to have “lost” her system prompt or tools in the portal:
  - verify the exact `FOUNDRY_AGENT_NAME`
  - verify the application name and routed deployment in Azure
  - verify the registry row is not pointing at a different version than the active route
- Do **not** assume that deleting or rebooting the container fixes the issue.
- If the Foundry lineage is polluted or ambiguous, create a new canonical app name and let the runtime create a fresh version/deployment set.

## Recommended Canonical Pattern

- Keep one active self-hosted runtime lineage only.
- Use explicit environment variables:
  - `FOUNDRY_AGENT_NAME`
  - `FOUNDRY_APPLICATION_NAME`
- Keep these values identical unless there is a deliberate reason to separate them.
- Archive or delete stale application lineages only **after** the new canonical app is healthy and verified.
