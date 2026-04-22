import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from foundry_publish import (
    PublishedDeploymentState,
    extract_active_deployment_state,
    extract_latest_deployment_state,
    parse_project_scope_from_connection_id,
    reconcile_managed_publication,
    select_effective_agent_version,
)


class FakeCredential:
    class Token:
        token = "test-token"

    def get_token(self, _scope: str):
        return self.Token()


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, application, deployments, *, updated_deployment_id: str | None = None):
        self.application = application
        self.deployments = {item["name"]: item for item in deployments}
        self.updated_deployment_id = updated_deployment_id
        self.requests = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.requests.append({"method": method, "url": url, "json": json})
        if "/agentdeployments?" in url and method == "GET":
            return FakeResponse(200, {"value": list(self.deployments.values())})
        if "/agentdeployments/" in url and method == "PUT":
            deployment_name = url.split("/agentdeployments/")[1].split("?")[0]
            current = self.deployments.get(
                deployment_name,
                {
                    "name": deployment_name,
                    "properties": {},
                },
            )
            deployment_id = self.updated_deployment_id or current.get("properties", {}).get("deploymentId") or f"{deployment_name}-id"
            agent_props = json["properties"]["agents"][0]
            updated = {
                "name": deployment_name,
                "properties": {
                    "deploymentId": deployment_id,
                    "agents": [
                        {
                            "agentName": agent_props["agentName"],
                            "agentVersion": str(agent_props["agentVersion"]),
                        }
                    ],
                },
            }
            self.deployments[deployment_name] = updated
            return FakeResponse(200, updated)
        if "/applications/" in url and "/agentdeployments/" not in url and method == "GET":
            if self.application is None:
                return FakeResponse(404, {"error": "not found"})
            return FakeResponse(200, self.application)
        if "/applications/" in url and "/agentdeployments/" not in url and method == "PUT":
            properties = dict((self.application or {}).get("properties", {}))
            properties.update(json["properties"])
            self.application = {
                "name": url.split("/applications/")[1].split("?")[0],
                "properties": properties,
            }
            return FakeResponse(200, self.application)
        raise AssertionError(f"Unhandled request: {method} {url}")


class FailingUpdateSession(FakeSession):
    def request(self, method, url, headers=None, json=None, timeout=None):
        if "/agentdeployments/" in url and method == "PUT":
            return FakeResponse(
                404,
                {
                    "error": {
                        "code": "SystemError",
                        "message": "SystemError",
                    }
                },
            )
        return super().request(method, url, headers=headers, json=json, timeout=timeout)


class FoundryPublishTests(unittest.TestCase):
    def test_parse_project_scope_from_connection_id(self):
        scope = parse_project_scope_from_connection_id(
            "/subscriptions/sub-123/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/"
            "accounts/foundry-acc/projects/project-1/connections/search-conn"
        )
        self.assertEqual(scope.subscription_id, "sub-123")
        self.assertEqual(scope.resource_group, "rg-test")
        self.assertEqual(scope.account_name, "foundry-acc")
        self.assertEqual(scope.project_name, "project-1")

    def test_extract_active_deployment_state_uses_traffic_rule(self):
        application = {
            "properties": {
                "trafficRoutingPolicy": {
                    "rules": [
                        {
                            "deploymentId": "dep-2",
                        }
                    ]
                }
            }
        }
        deployments = [
            {
                "name": "lucy-chat-v2-1",
                "properties": {
                    "deploymentId": "dep-1",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "1"}],
                },
            },
            {
                "name": "lucy-chat-v2-8",
                "properties": {
                    "deploymentId": "dep-2",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "8"}],
                },
            },
        ]
        state = extract_active_deployment_state("lucy-chat-v2", application, deployments)
        self.assertEqual(state.deployment_name, "lucy-chat-v2-8")
        self.assertEqual(state.agent_version, "8")

    def test_select_effective_agent_version_prefers_published_state_when_local_has_no_drift(self):
        record = {"agent_name": "lucy-chat-v2", "agent_version": "1"}
        published = PublishedDeploymentState(
            application_name="lucy-chat-v2",
            deployment_name="lucy-chat-v2-8",
            deployment_id="dep-8",
            agent_name="lucy-chat-v2",
            agent_version="8",
        )
        self.assertEqual(
            select_effective_agent_version(record, published, []),
            "8",
        )

    def test_extract_latest_deployment_state_prefers_highest_version(self):
        deployments = [
            {
                "name": "lucy-chat-v2-1",
                "properties": {
                    "deploymentId": "dep-1",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "1"}],
                },
            },
            {
                "name": "lucy-chat-v2-8",
                "properties": {
                    "deploymentId": "dep-8",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "8"}],
                },
            },
        ]
        state = extract_latest_deployment_state("lucy-chat-v2", deployments, agent_name="lucy-chat-v2")
        self.assertEqual(state.deployment_name, "lucy-chat-v2-8")
        self.assertEqual(state.agent_version, "8")

    def test_select_effective_agent_version_prefers_active_route_for_runtime(self):
        record = {"agent_name": "lucy-chat-v2", "agent_version": "1"}
        active = PublishedDeploymentState(
            application_name="lucy-chat-v2",
            deployment_name="lucy-chat-v2-1",
            deployment_id="dep-1",
            agent_name="lucy-chat-v2",
            agent_version="1",
        )
        latest = PublishedDeploymentState(
            application_name="lucy-chat-v2",
            deployment_name="lucy-chat-v2-8",
            deployment_id="dep-8",
            agent_name="lucy-chat-v2",
            agent_version="8",
        )
        self.assertEqual(
            select_effective_agent_version(record, active, [], latest),
            "1",
        )

    def test_reconcile_managed_publication_is_noop_when_active_version_matches(self):
        scope = parse_project_scope_from_connection_id(
            "/subscriptions/sub-123/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/"
            "accounts/foundry-acc/projects/project-1/connections/search-conn"
        )
        application = {
            "name": "lucy-chat-v2",
            "properties": {
                "agents": [{"agentName": "lucy-chat-v2"}],
                "trafficRoutingPolicy": {
                    "rules": [{"deploymentId": "dep-8"}],
                },
            },
        }
        deployments = [
            {
                "name": "lucy-chat-v2",
                "properties": {
                    "deploymentId": "dep-8",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "8"}],
                },
            }
        ]
        session = FakeSession(application, deployments)

        state = reconcile_managed_publication(
            scope,
            "lucy-chat-v2",
            "lucy-chat-v2",
            "8",
            FakeCredential(),
            session=session,
        )

        self.assertEqual(state.agent_version, "8")
        self.assertEqual([req["method"] for req in session.requests], ["GET", "GET"])

    def test_reconcile_managed_publication_updates_stale_deployment_and_reroutes(self):
        scope = parse_project_scope_from_connection_id(
            "/subscriptions/sub-123/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/"
            "accounts/foundry-acc/projects/project-1/connections/search-conn"
        )
        application = {
            "name": "lucy-chat-v2",
            "properties": {
                "agents": [{"agentName": "lucy-chat-v2"}],
                "trafficRoutingPolicy": {
                    "rules": [{"deploymentId": "dep-1"}],
                },
            },
        }
        deployments = [
            {
                "name": "lucy-chat-v2",
                "properties": {
                    "deploymentId": "dep-1",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "1"}],
                },
            }
        ]
        session = FakeSession(application, deployments, updated_deployment_id="dep-9")

        state = reconcile_managed_publication(
            scope,
            "lucy-chat-v2",
            "lucy-chat-v2",
            "9",
            FakeCredential(),
            session=session,
        )

        self.assertEqual(state.agent_version, "9")
        app_put = next(req for req in session.requests if req["method"] == "PUT" and "/applications/" in req["url"] and "/agentdeployments/" not in req["url"])
        self.assertEqual(
            app_put["json"]["properties"]["trafficRoutingPolicy"]["rules"][0]["deploymentId"],
            "dep-9",
        )

    def test_reconcile_managed_publication_falls_back_to_latest_existing_version_on_update_error(self):
        scope = parse_project_scope_from_connection_id(
            "/subscriptions/sub-123/resourceGroups/rg-test/providers/Microsoft.CognitiveServices/"
            "accounts/foundry-acc/projects/project-1/connections/search-conn"
        )
        application = {
            "name": "lucy-chat-v2",
            "properties": {
                "agents": [{"agentName": "lucy-chat-v2"}],
                "trafficRoutingPolicy": {
                    "rules": [{"deploymentId": "dep-1"}],
                },
            },
        }
        deployments = [
            {
                "name": "lucy-chat-v2-1",
                "properties": {
                    "deploymentId": "dep-1",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "1"}],
                },
            },
            {
                "name": "lucy-chat-v2-8",
                "properties": {
                    "deploymentId": "dep-8",
                    "agents": [{"agentName": "lucy-chat-v2", "agentVersion": "8"}],
                },
            },
        ]
        session = FailingUpdateSession(application, deployments)

        state = reconcile_managed_publication(
            scope,
            "lucy-chat-v2",
            "lucy-chat-v2",
            "8",
            FakeCredential(),
            session=session,
        )

        self.assertEqual(state.deployment_name, "lucy-chat-v2-8")
        self.assertEqual(state.agent_version, "8")


if __name__ == "__main__":
    unittest.main()
