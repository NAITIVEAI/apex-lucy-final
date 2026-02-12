# SOC 2 Renewal Support Package (Application: Lucy)

## 1. Purpose and Scope
This document supports SOC 2 renewal evidence collection for the broader organization and summarizes the security and operational controls implemented for the Lucy application.

This is **supporting evidence** and not an independent audit opinion.

In scope:
- Customer-facing AI assistant service (`agent/app`)
- Internal human handoff portal (`portal/app`)
- Integrations with Azure AI Search, Azure OpenAI/Foundry, Azure Storage Tables/Blobs, Dynamics 365, and Teams

Out of scope for this handoff package:
- CI/CD pipelines
- Ongoing deployment automation scripts
- Historical/debug/agent-tooling artifacts (moved to `/removal`)

## 2. System Overview
Lucy consists of two runtime services:
- Agent service: conversational assistant runtime and tool orchestration
- Portal service: internal operations interface for handoff/callback workflows

Primary data/security boundaries:
- User session and tool interactions in app runtime
- Storage-backed persistence for conversation/callback records
- External API calls to Azure-managed services and enterprise systems (Dynamics/Teams)

## 3. Control Implementation Summary (SOC 2-Relevant)

### 3.1 Secret Management and Configuration
- Secrets are environment-driven and not hardcoded in retained runtime code.
- Runtime modules rely on environment variables for credentials and endpoints.
- Operational recommendation: enforce secret injection via Azure Container Apps secrets and/or Key Vault references.

Evidence locations:
- `agent/app/.env.example`
- `portal/app/.env.example`
- `agent/app/user_functions.py`
- `portal/app/user_functions.py`

### 3.2 Access Control and Authentication
- Member-level verification flows exist in the assistant runtime before sensitive member operations.
- Portal authentication now supports optional token enforcement using `AGENT_PORTAL_API_TOKEN`.
- If `AGENT_PORTAL_API_TOKEN` is set, portal requests without a valid bearer token (or `X-Agent-Token`) are rejected with HTTP 401.

Evidence locations:
- `agent/app/agentic_authentication.py`
- `agent/app/agentic_authentication_enhanced_v2.py`
- `portal/app/agent_portal.py`

### 3.3 Secure-by-Default Diagnostic Surface
- Portal debug endpoints are disabled by default via `ENABLE_DEBUG_ENDPOINTS=false`.
- Sensitive connection-string prefix exposure in debug output was removed.
- Debug endpoints now return 404 unless explicitly enabled.

Evidence location:
- `portal/app/agent_portal.py`

### 3.4 Auditability and Observability
- Structured logging and tracing utilities are present for operational diagnostics.
- Callback and conversation store workflows record operational events.

Evidence locations:
- `agent/app/tracing_config.py`
- `agent/app/tracing_utils.py`
- `agent/app/callback_system.py`
- `portal/app/callback_system.py`
- `portal/app/conversation_store.py`

### 3.5 Data Integrity and Processing Controls
- Explicit function/tool paths are implemented for member lookup, updates, notice retrieval, and callback handling.
- Runtime code includes fallback and status handling for operational resilience.

Evidence locations:
- `agent/app/user_functions.py`
- `agent/app/apex.py`
- `agent/app/notice_match.py`

### 3.6 Startup Configuration Gates (Storage Policy)
- Startup validation now enforces storage configuration by default.
- Policy variables:
  - `REQUIRE_AZURE_STORAGE_CONNECTION_STRING=true` (default enforced)
  - `ALLOW_STORAGE_FALLBACK=false` (default; set true only for controlled exception scenarios)
- If storage is required and `AZURE_STORAGE_CONNECTION_STRING` is missing, startup fails fast.

Evidence locations:
- `agent/app/startup_verification.py`
- `agent/app/start_services.sh`
- `portal/app/start_agent_portal.sh`

## 4. Evidence Checklist for SOC 2 Renewal Binder
Collect or attach the following evidence outside source code where applicable:

### Governance and Policy Evidence
- Security policy
- Access control policy
- Incident response policy
- Change management policy
- Vendor management policy
- Data retention and disposal policy

### Access and Identity Evidence
- Role matrix and least-privilege mapping for Azure, Dynamics, Teams
- Admin/user access review results (last 2 review cycles)
- Evidence of terminated-user access revocation testing

### Change Management Evidence
- Code review records and approval history
- Release/change tickets for production-impacting updates
- Segregation-of-duties evidence for code author vs approver

### Security Operations Evidence
- Vulnerability scan results and remediation records
- Patch/upgrade records for runtime dependencies
- Logging/monitoring alert definitions and incident tickets

### Availability and Recovery Evidence
- Backup/restore strategy for data stores
- Recovery test evidence and RTO/RPO targets
- Service health monitoring and escalation procedures

### Confidentiality/Privacy Evidence
- Data classification for member data fields
- Encryption-in-transit and encryption-at-rest configuration evidence
- Third-party data processing agreements and subprocessors list

## 5. Application-Specific Renewal Notes
- Non-runtime and implementation-history artifacts were isolated into `/removal` to provide a cleaner, client-facing code package.
- Runtime code paths remain under `agent/app` and `portal/app`.
- Security hardening performed in this handoff:
  - Optional token-based portal authentication
  - Debug endpoints disabled by default
  - Removal of connection string preview in debug responses

## 6. Residual Risks / Follow-Up Items
1. Ensure `AGENT_PORTAL_API_TOKEN` is configured in deployed environments; otherwise portal access remains permissive.
2. Validate CORS and upload constraints for production threat model (`agent/app/.chainlit/config.toml` currently permits broad origins and file types).
3. Confirm centralized log retention, alerting, and evidence export procedures are active in production.

## 7. Auditor-Ready Statement
Based on source-code and configuration review in this handoff package, Lucy demonstrates foundational controls aligned with SOC 2 Security and Availability principles, with clear opportunities for further hardening through environment-enforced authentication and stricter runtime configuration controls.
