from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from server.mcp_server import McpServer


class SeeIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = McpServer()
        self.server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "see-test", "version": "0.0.0"}},
        })

    def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        response = self.server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })[0]["result"]
        self.assertFalse(response["isError"], response)
        return response["structuredContent"]["content"]

    def test_environmental_goal_discovers_see_and_its_models(self) -> None:
        content = self.call("map_user_goal_to_ce_rise_capabilities", {
            "user_goal": "Integrate environmental footprint assessment for recycled aluminium",
        })
        self.assertIn("see_impacts_calculation_service", {
            item["id"] for item in content["suggested_components"]
        })
        self.assertTrue({"see_impacts_calculation_service", "product_system_model",
                         "lci_dataset_model", "integrated_lca_model"}.issubset({
            item["id"] for item in content["source_references"]
        }))
        architecture = self.call("recommend_passport_architecture", {
            "use_case": "Environmental footprint assessment", "priorities": ["lca"],
        })
        self.assertEqual(architecture["recommended_pattern"]["id"], "environmental_footprint_integration")
        self.assertIn("see_impacts_calculation_service_local", {
            item["id"] for item in architecture["live_service_connections"]
        })

    def test_see_probe_is_read_only_and_cannot_compute(self) -> None:
        services = self.call("list_live_service_connections", {})["services"]
        service = next(item for item in services if item["id"] == "see_impacts_calculation_service_local")
        self.assertEqual(service["default_base_url"], "http://127.0.0.1:8084")
        self.assertTrue(all(item["method"] == "GET" for item in service["safe_endpoints"]))
        self.assertEqual(service["blocked_endpoint_patterns"], ["POST /compute"])
        with patch("server.mcp_server._http_get", return_value={"available": True}) as request:
            self.call("probe_live_service", {"service_id": service["id"]})
            self.assertEqual({call.args[0] for call in request.call_args_list}, {
                "http://127.0.0.1:8084/health", "http://127.0.0.1:8084/capabilities",
                "http://127.0.0.1:8084/methods", "http://127.0.0.1:8084/openapi.json",
            })
            request.reset_mock()
            self.call("inspect_live_service_openapi", {"service_id": service["id"]})
            self.assertEqual(request.call_args.args[0], "http://127.0.0.1:8084/openapi.json")
            request.reset_mock()
            rejected = self.server.handle_message({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "probe_live_service", "arguments": {
                    "service_id": service["id"], "endpoint_ids": ["compute"],
                }},
            })[0]["result"]
            self.assertTrue(rejected["isError"])
            request.assert_not_called()

    def test_plan_and_generation_infer_see_selection_and_allow_exclusion(self) -> None:
        for name in ("generate_deployment_artifact_plan", "generate_deployment_artifacts"):
            for enabled in (True, False):
                with self.subTest(tool=name, enabled=enabled):
                    arguments = {"target": "both", "selected_components": ["see_impacts_calculation_service"]}
                    if not enabled:
                        arguments["include_see_impacts"] = False
                    content = self.call(name, arguments)
                    templates = content.get("recommended_templates", content.get("templates"))
                    ids = {item["id"] for item in templates}
                    self.assertEqual("compose_see_impacts_profile" in ids, enabled)
                    self.assertEqual("kubernetes_see_impacts_extension" in ids, enabled)
                    self.assertNotIn("compose_re_indicators_profile", ids)
                    self.assertNotIn("kubernetes_calculations_overlays", ids)

    def test_generation_keeps_calculation_services_independent(self) -> None:
        for re_enabled in (False, True):
            for see_enabled in (False, True):
                with self.subTest(re=re_enabled, see=see_enabled):
                    content = self.call("generate_deployment_artifacts", {
                        "target": "both", "include_re_indicators": re_enabled,
                        "include_see_impacts": see_enabled, "project_name": "adopter pilot",
                    })
                    files = {item["path"]: item["content"] for item in content["files"]}
                    compose = files["compose/docker-compose.yml"]
                    self.assertEqual("re-indicators-calculation-service:" in compose, re_enabled)
                    self.assertEqual("see-impacts-calculation-service:" in compose, see_enabled)
                    self.assertEqual("k8s/extensions/see-impacts/deployment.yaml" in files, see_enabled)
                    self.assertEqual("k8s/extensions/re-indicators/deployment.yaml" in files, re_enabled)
                    self.assertEqual("k8s/overlays/dev-calculations/kustomization.yaml" in files,
                                     re_enabled and see_enabled)
                    for template in content["templates"]:
                        self.assertTrue(set(template["included_files"]).issubset(files), template["id"])
                    self.assertNotIn(":latest", files["compose/.env.example"])
                    self.assertIn("hex-core-service:v0.0.9", files["k8s/base/hex-core-deployment.yaml"])
                    models = {item["model"]: item for item in json.loads(files["compose/registry/catalog.json"])["models"]}
                    for model, version in (("product-system", "0.0.1"), ("lci-dataset", "0.0.1"),
                                           ("integrated-lca", "0.2.0")):
                        self.assertEqual(models[model]["version"], version)
                        self.assertIn(f"/pages-v{version}/generated/schema.json", models[model]["schema_url"])
                    if see_enabled:
                        self.assertIn("--profile see-impacts config", content["validation_commands"][0])
                        self.assertIn("127.0.0.1:${SEE_IMPACTS_CALC_PORT:-8084}:8080", compose)
                        self.assertIn("HEX_CORE_BEARER_TOKEN: ${SEE_IMPACTS_HEX_CORE_BEARER_TOKEN:-}", compose)
                        deployment = files["k8s/extensions/see-impacts/deployment.yaml"]
                        self.assertIn("see-impacts-calculation:v0.0.1", deployment)
                        self.assertIn("fsGroup: 1000", deployment)
                        self.assertIn("emptyDir: {}", deployment)
                        self.assertIn("path: /capabilities", deployment)
                        self.assertIn("name: see-impacts-auth", deployment)
                        self.assertIn("optional: true", deployment)
                        self.assertNotIn("pv", deployment.lower())
                        self.assertIn("see_impacts_calculation_service_codeberg_releases", {
                            item["id"] for item in content["version_context"]["update_channels"]
                        })
                    if re_enabled and see_enabled:
                        for env in ("dev", "prod"):
                            path = f"k8s/overlays/{env}-calculations/kustomization.yaml"
                            self.assertIn(f"namespace: adopter-pilot-{env}", files[path])
                            self.assertIn("../../extensions/re-indicators", files[path])
                            self.assertIn("../../extensions/see-impacts", files[path])
                            self.assertIn(f"kubectl kustomize k8s/overlays/{env}-calculations",
                                          content["validation_commands"])

    def test_see_selection_rejects_non_boolean_arguments(self) -> None:
        for name in ("generate_deployment_artifact_plan", "generate_deployment_artifacts"):
            with self.subTest(tool=name):
                response = self.server.handle_message({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": name, "arguments": {
                        "target": "compose", "include_see_impacts": "true",
                    }},
                })[0]["result"]
                self.assertTrue(response["isError"])

    def test_checked_see_model_versions_are_used_in_both_catalogs(self) -> None:
        def response(url: str, method: str, timeout_seconds: float) -> dict[str, object]:
            body = '[{"name":"pages-v2.3.4"}]' if "/tags" in url else '[{"tag_name":"v0.0.1"}]'
            return {"url": url, "available": True, "status": 200, "reason": "OK",
                    "headers": {}, "body_text": body, "body_bytes": len(body), "body_truncated": False}

        with patch("server.mcp_server._http_request_raw", side_effect=response):
            content = self.call("generate_deployment_artifacts", {
                "target": "both", "include_see_impacts": True, "check_remote_updates": True,
            })
        files = {item["path"]: item["content"] for item in content["files"]}
        for model in ("product-system", "lci-dataset", "integrated-lca"):
            self.assertIn(f"{model}/raw/tag/pages-v2.3.4/generated/schema.json", files["compose/registry/catalog.json"])
            self.assertIn(f"{model}/raw/tag/pages-v2.3.4/generated/schema.json", files["k8s/base/registry-configmap.yaml"])

    def test_reference_example_retains_pv_as_example_not_product_restriction(self) -> None:
        content = self.call("generalize_reference_example", {
            "example_id": "dp_system_local_demonstrator", "target_outcome": "environmental assessment integration",
            "adoption_context": {"passport_scope": "steel components"},
        })
        self.assertIn("see_impacts_calculation_service", {
            item["id"] for item in content["source_references"]
        })
        assumptions = [item for step in content["generalized_steps"] for item in step["not_assumptions"]]
        self.assertTrue(any("PV" in item and "restricts" in item for item in assumptions))

    def test_deployment_tool_schemas_advertise_see_selection(self) -> None:
        response = self.server.handle_message({
            "jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {},
        })[0]["result"]
        for tool in response["tools"]:
            if tool["name"] in {"generate_deployment_artifact_plan", "generate_deployment_artifacts"}:
                self.assertEqual(tool["inputSchema"]["properties"]["include_see_impacts"]["type"], "boolean")


if __name__ == "__main__":
    unittest.main()
