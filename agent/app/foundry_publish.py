import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


DEFAULT_MANAGEMENT_API_VERSION = "2026-01-15-preview"


@dataclass(frozen=True)
class FoundryProjectScope:
    subscription_id: str
    resource_group: str
    account_name: str
    project_name: str


@dataclass(frozen=True)
class PublishedDeploymentState:
    application_name: str
    deployment_name: str
    deployment_id: str
    agent_name: str
    agent_version: str


_CONNECTION_SCOPE_PATTERN = re.compile(
    r"^/subscriptions/(?P<subscription_id>[^/]+)/resourceGroups/(?P<resource_group>[^/]+)/"
    r"providers/Microsoft\.CognitiveServices/accounts/(?P<account_name>[^/]+)/"
    r"projects/(?P<project_name>[^/]+)/connections/(?P<connection_name>[^/]+)$",
    re.IGNORECASE,
)


def get_management_api_version() -> str:
    return os.getenv("FOUNDRY_MANAGEMENT_API_VERSION") or DEFAULT_MANAGEMENT_API_VERSION


def parse_project_scope_from_connection_id(connection_id: str) -> FoundryProjectScope:
    if not connection_id:
        raise ValueError("connection_id is required")
    match = _CONNECTION_SCOPE_PATTERN.match(connection_id.strip())
    if not match:
        raise ValueError(f"Unrecognized Foundry connection resource id: {connection_id}")
    return FoundryProjectScope(
        subscription_id=match.group("subscription_id"),
        resource_group=match.group("resource_group"),
        account_name=match.group("account_name"),
        project_name=match.group("project_name"),
    )


def get_application_name(agent_name: str, explicit_name: Optional[str] = None) -> str:
    chosen = (explicit_name or os.getenv("FOUNDRY_APPLICATION_NAME") or agent_name or "").strip()
    if not chosen:
        raise ValueError("Foundry application name is required")
    return chosen


def select_effective_agent_version(
    record: Optional[Dict[str, Any]],
    published_state: Optional[PublishedDeploymentState],
    mismatch_reasons: List[str],
    latest_published_state: Optional[PublishedDeploymentState] = None,
) -> Optional[str]:
    if mismatch_reasons:
        return None
    # The project Responses endpoint invokes an agent version directly. In live Azure,
    # we have seen cases where newer managed deployment metadata exists in the
    # application layer, but the project endpoint still only resolves the currently
    # active routed version. Prefer the active published version for runtime
    # invocation and treat any newer published deployments as diagnostic signal only.
    if published_state and published_state.agent_version:
        return str(published_state.agent_version)
    if record and record.get("agent_version"):
        return str(record.get("agent_version"))
    return None


def extract_active_deployment_state(
    application_name: str,
    application: Optional[Dict[str, Any]],
    deployments: List[Dict[str, Any]],
) -> Optional[PublishedDeploymentState]:
    if not application:
        return None

    rules = (
        application.get("properties", {})
        .get("trafficRoutingPolicy", {})
        .get("rules", [])
    )
    routed_deployment_id = next(
        (str(rule.get("deploymentId")) for rule in rules if rule.get("deploymentId")),
        None,
    )

    chosen = None
    if routed_deployment_id:
        chosen = next(
            (
                deployment
                for deployment in deployments
                if deployment.get("properties", {}).get("deploymentId") == routed_deployment_id
            ),
            None,
        )

    if chosen is None and len(deployments) == 1:
        chosen = deployments[0]

    if chosen is None:
        chosen = next((deployment for deployment in deployments if deployment.get("name") == application_name), None)

    if chosen is None:
        return None

    agents = chosen.get("properties", {}).get("agents", [])
    if not agents:
        return None

    active_agent = agents[0]
    return PublishedDeploymentState(
        application_name=application_name,
        deployment_name=str(chosen.get("name") or application_name),
        deployment_id=str(chosen.get("properties", {}).get("deploymentId") or ""),
        agent_name=str(active_agent.get("agentName") or application_name),
        agent_version=str(active_agent.get("agentVersion") or ""),
    )


def extract_latest_deployment_state(
    application_name: str,
    deployments: List[Dict[str, Any]],
    *,
    agent_name: Optional[str] = None,
) -> Optional[PublishedDeploymentState]:
    candidates: List[PublishedDeploymentState] = []
    for deployment in deployments:
        agents = deployment.get("properties", {}).get("agents", [])
        if not agents:
            continue
        active_agent = agents[0]
        current_agent_name = str(active_agent.get("agentName") or application_name)
        if agent_name and current_agent_name != agent_name:
            continue
        candidates.append(
            PublishedDeploymentState(
                application_name=application_name,
                deployment_name=str(deployment.get("name") or application_name),
                deployment_id=str(deployment.get("properties", {}).get("deploymentId") or ""),
                agent_name=current_agent_name,
                agent_version=str(active_agent.get("agentVersion") or ""),
            )
        )

    if not candidates:
        return None

    def _version_key(state: PublishedDeploymentState):
        version = state.agent_version
        if version.isdigit():
            return (1, int(version))
        return (0, version)

    return max(candidates, key=_version_key)


def _arm_base(scope: FoundryProjectScope) -> str:
    return (
        "https://management.azure.com/"
        f"subscriptions/{scope.subscription_id}/resourceGroups/{scope.resource_group}/"
        f"providers/Microsoft.CognitiveServices/accounts/{scope.account_name}/"
        f"projects/{scope.project_name}"
    )


def _application_url(scope: FoundryProjectScope, application_name: str) -> str:
    return (
        f"{_arm_base(scope)}/applications/{application_name}"
        f"?api-version={get_management_api_version()}"
    )


def _deployments_url(scope: FoundryProjectScope, application_name: str) -> str:
    return (
        f"{_arm_base(scope)}/applications/{application_name}/agentdeployments"
        f"?api-version={get_management_api_version()}"
    )


def _deployment_url(scope: FoundryProjectScope, application_name: str, deployment_name: str) -> str:
    return (
        f"{_arm_base(scope)}/applications/{application_name}/agentdeployments/{deployment_name}"
        f"?api-version={get_management_api_version()}"
    )


def _request_json(
    session: Any,
    credential: Any,
    method: str,
    url: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    allow_not_found: bool = False,
) -> Optional[Dict[str, Any]]:
    token = credential.get_token("https://management.azure.com/.default").token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = session.request(method, url, headers=headers, json=payload, timeout=30)
    if allow_not_found and response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(
            f"Foundry management API {method} {url} failed: "
            f"{response.status_code} {response.text}"
        )
    if not response.text:
        return {}
    return response.json()


def get_application(
    scope: FoundryProjectScope,
    application_name: str,
    credential: Any,
    *,
    session: Any = requests,
) -> Optional[Dict[str, Any]]:
    return _request_json(
        session,
        credential,
        "GET",
        _application_url(scope, application_name),
        allow_not_found=True,
    )


def list_agent_deployments(
    scope: FoundryProjectScope,
    application_name: str,
    credential: Any,
    *,
    session: Any = requests,
) -> List[Dict[str, Any]]:
    payload = _request_json(
        session,
        credential,
        "GET",
        _deployments_url(scope, application_name),
        allow_not_found=True,
    )
    if not payload:
        return []
    return payload.get("value", [])


def get_published_deployment_state(
    scope: FoundryProjectScope,
    application_name: str,
    credential: Any,
    *,
    session: Any = requests,
) -> Optional[PublishedDeploymentState]:
    application = get_application(scope, application_name, credential, session=session)
    if not application:
        return None
    deployments = list_agent_deployments(scope, application_name, credential, session=session)
    return extract_active_deployment_state(application_name, application, deployments)


def get_latest_published_deployment_state(
    scope: FoundryProjectScope,
    application_name: str,
    credential: Any,
    *,
    agent_name: Optional[str] = None,
    session: Any = requests,
) -> Optional[PublishedDeploymentState]:
    application = get_application(scope, application_name, credential, session=session)
    if not application:
        return None
    deployments = list_agent_deployments(scope, application_name, credential, session=session)
    return extract_latest_deployment_state(
        application_name,
        deployments,
        agent_name=agent_name,
    )


def _build_application_payload(
    application_name: str,
    agent_name: str,
    *,
    existing: Optional[Dict[str, Any]] = None,
    deployment_id: Optional[str] = None,
) -> Dict[str, Any]:
    existing_props = (existing or {}).get("properties", {})
    payload: Dict[str, Any] = {
        "properties": {
            "agents": [{"agentName": agent_name}],
        }
    }

    display_name = existing_props.get("displayName")
    if display_name:
        payload["properties"]["displayName"] = display_name
    elif existing is None:
        payload["properties"]["displayName"] = application_name

    description = existing_props.get("description")
    if description:
        payload["properties"]["description"] = description

    authorization_policy = existing_props.get("authorizationPolicy")
    if authorization_policy:
        payload["properties"]["authorizationPolicy"] = authorization_policy

    if existing_props.get("isEnabled") is not None:
        payload["properties"]["isEnabled"] = existing_props.get("isEnabled")

    if deployment_id:
        payload["properties"]["trafficRoutingPolicy"] = {
            "protocol": "FixedRatio",
            "rules": [
                {
                    "ruleId": "default",
                    "description": "Default rule routing all traffic to the first deployment",
                    "deploymentId": deployment_id,
                    "trafficPercentage": 100,
                }
            ],
        }
    elif existing_props.get("trafficRoutingPolicy"):
        payload["properties"]["trafficRoutingPolicy"] = existing_props.get("trafficRoutingPolicy")

    return payload


def create_or_update_application(
    scope: FoundryProjectScope,
    application_name: str,
    agent_name: str,
    credential: Any,
    *,
    existing: Optional[Dict[str, Any]] = None,
    deployment_id: Optional[str] = None,
    session: Any = requests,
) -> Dict[str, Any]:
    payload = _build_application_payload(
        application_name,
        agent_name,
        existing=existing,
        deployment_id=deployment_id,
    )
    return _request_json(
        session,
        credential,
        "PUT",
        _application_url(scope, application_name),
        payload=payload,
    ) or {}


def create_or_update_managed_deployment(
    scope: FoundryProjectScope,
    application_name: str,
    deployment_name: str,
    agent_name: str,
    agent_version: str,
    credential: Any,
    *,
    session: Any = requests,
) -> Dict[str, Any]:
    payload = {
        "properties": {
            "displayName": application_name,
            "description": "Self-hosted Lucy prompt agent managed deployment",
            "deploymentType": "Managed",
            "protocols": [{"protocol": "Responses", "version": "1.0"}],
            "agents": [
                {
                    "agentName": agent_name,
                    "agentVersion": str(agent_version),
                }
            ],
        }
    }
    return _request_json(
        session,
        credential,
        "PUT",
        _deployment_url(scope, application_name, deployment_name),
        payload=payload,
    ) or {}


def reconcile_managed_publication(
    scope: FoundryProjectScope,
    application_name: str,
    agent_name: str,
    desired_agent_version: str,
    credential: Any,
    *,
    session: Any = requests,
) -> PublishedDeploymentState:
    application = get_application(scope, application_name, credential, session=session)
    if not application:
        application = create_or_update_application(
            scope,
            application_name,
            agent_name,
            credential,
            existing=None,
            session=session,
        )

    deployments = list_agent_deployments(scope, application_name, credential, session=session)
    active_state = extract_active_deployment_state(application_name, application, deployments)
    latest_state = extract_latest_deployment_state(
        application_name,
        deployments,
        agent_name=agent_name,
    )

    if (
        active_state
        and active_state.agent_name == agent_name
        and active_state.agent_version == str(desired_agent_version)
    ):
        return active_state

    if (
        latest_state
        and latest_state.agent_name == agent_name
        and latest_state.agent_version == str(desired_agent_version)
    ):
        try:
            if active_state and active_state.deployment_name:
                deployment = create_or_update_managed_deployment(
                    scope,
                    application_name,
                    active_state.deployment_name,
                    agent_name,
                    str(desired_agent_version),
                    credential,
                    session=session,
                )
                deployment_id = str(deployment.get("properties", {}).get("deploymentId") or "")
                if deployment_id:
                    application = create_or_update_application(
                        scope,
                        application_name,
                        agent_name,
                        credential,
                        existing=application,
                        deployment_id=deployment_id,
                        session=session,
                    )
                    deployments = list_agent_deployments(scope, application_name, credential, session=session)
                    final_state = extract_active_deployment_state(application_name, application, deployments)
                    if final_state:
                        return final_state
        except Exception:
            # Azure management update can fail even when the desired version is already
            # present as a published deployment. In that case, keep Lucy running against
            # the latest published version instead of failing chat startup.
            return latest_state

    deployment_name = active_state.deployment_name if active_state else application_name
    deployment = create_or_update_managed_deployment(
        scope,
        application_name,
        deployment_name,
        agent_name,
        str(desired_agent_version),
        credential,
        session=session,
    )
    deployment_id = str(deployment.get("properties", {}).get("deploymentId") or "")
    if not deployment_id:
        raise RuntimeError("Managed deployment did not return a deploymentId")

    needs_application_update = (
        application is None
        or active_state is None
        or active_state.deployment_id != deployment_id
    )
    if needs_application_update:
        application = create_or_update_application(
            scope,
            application_name,
            agent_name,
            credential,
            existing=application,
            deployment_id=deployment_id,
            session=session,
        )

    deployments = list_agent_deployments(scope, application_name, credential, session=session)
    final_state = extract_active_deployment_state(application_name, application, deployments)
    if final_state is None:
        raise RuntimeError("Unable to resolve active published deployment after reconciliation")
    if final_state.agent_version != str(desired_agent_version):
        raise RuntimeError(
            "Published deployment reconciliation did not activate the expected version: "
            f"expected {desired_agent_version}, got {final_state.agent_version}"
        )
    return final_state
