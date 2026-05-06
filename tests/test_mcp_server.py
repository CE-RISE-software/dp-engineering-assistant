from __future__ import annotations

import unittest
from unittest.mock import patch

from server.mcp_server import McpServer


class McpServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = McpServer()

    def initialize(self) -> dict[str, object]:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "unit-test", "version": "0.0.0"},
                },
            }
        )
        self.assertEqual(len(response), 1)
        return response[0]

    def test_initialize_advertises_tools_and_resources(self) -> None:
        response = self.initialize()
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("resources", result["capabilities"])

    def test_tools_list_requires_initialize(self) -> None:
        response = self.server.handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        self.assertIn("error", response[0])
        self.assertEqual(response[0]["error"]["code"], -32600)

    def test_tools_list_returns_expected_tool_names(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        tools = response[0]["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(
            names,
            {
                "list_solution_capabilities",
                "list_solution_components",
                "map_user_goal_to_ce_rise_capabilities",
                "recommend_passport_architecture",
                "generate_implementation_plan",
                "assess_implementation_readiness",
                "assess_adoption_context",
                "map_value_chain_flows",
                "identify_value_opportunities",
                "recommend_adoption_path",
                "generate_implementation_roadmap",
                "list_deployment_artifact_templates",
                "generate_deployment_artifact_plan",
                "generate_deployment_artifacts",
                "assess_deployment_artifact_readiness",
                "list_reference_examples",
                "generalize_reference_example",
                "list_update_channels",
                "check_update_channels",
                "build_update_aware_solution_context",
                "discover_model_repositories",
                "list_connected_sources",
                "check_connected_sources",
                "inspect_connected_source",
                "build_connected_solution_snapshot",
                "list_live_service_connections",
                "probe_live_service",
                "inspect_live_service_openapi",
                "build_live_service_readiness_snapshot",
            },
        )

    def test_goal_mapping_returns_structured_content(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "map_user_goal_to_ce_rise_capabilities",
                    "arguments": {
                        "user_goal": "Plan a local product passport prototype with model validation",
                        "constraints": ["local", "SHACL"],
                    },
                },
            }
        )
        result = response[0]["result"]
        self.assertFalse(result["isError"])
        structured = result["structuredContent"]
        self.assertEqual(structured["result_type"], "goal_mapping_result")
        capability_ids = {
            item["id"] for item in structured["content"]["matched_capabilities"]
        }
        self.assertIn("data_model_and_semantic_alignment", capability_ids)
        source_ids = {item["id"] for item in structured["content"]["source_references"]}
        self.assertIn("dp_assessment_workbench", source_ids)
        live_service_ids = {item["id"] for item in structured["content"]["live_service_connections"]}
        self.assertIn("hex_core_service_local", live_service_ids)
        self.assertEqual(
            structured["content"]["update_awareness"]["status"],
            "current_metadata_not_checked",
        )
        update_channel_ids = {
            item["id"] for item in structured["content"]["update_awareness"]["update_channels"]
        }
        self.assertIn("hex_core_service_codeberg_releases", update_channel_ids)

    def test_readiness_assessment_reports_missing_fields(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "assess_implementation_readiness",
                    "arguments": {
                        "project_context": {
                            "passport_scope": "Digital Passport prototype",
                            "user_goal": "Try CE-RISE components locally",
                        }
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "implementation_readiness_result")
        self.assertGreater(structured["content"]["missing_fields"], 0)
        self.assertEqual(structured["content"]["readiness_level"], "early")

    def test_catalog_resource_can_be_read(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list", "params": {}}
        )
        resources = response[0]["result"]["resources"]
        self.assertIn("ce-rise://solution/catalog", {item["uri"] for item in resources})
        self.assertIn("ce-rise://sources/manifest", {item["uri"] for item in resources})
        self.assertIn("ce-rise://services/live-connections", {item["uri"] for item in resources})
        self.assertIn("ce-rise://deployment/artifact-templates", {item["uri"] for item in resources})
        self.assertIn("ce-rise://examples/reference-generalization", {item["uri"] for item in resources})
        self.assertIn("ce-rise://updates/channels", {item["uri"] for item in resources})
        read_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "resources/read",
                "params": {"uri": "ce-rise://solution/scope"},
            }
        )
        text = read_response[0]["result"]["contents"][0]["text"]
        self.assertIn("must not substitute", text)

        source_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "resources/read",
                "params": {"uri": "ce-rise://sources/manifest"},
            }
        )
        source_text = source_response[0]["result"]["contents"][0]["text"]
        self.assertIn("dp_assessment_workbench", source_text)

        service_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "resources/read",
                "params": {"uri": "ce-rise://services/live-connections"},
            }
        )
        service_text = service_response[0]["result"]["contents"][0]["text"]
        self.assertIn("hex_core_service_local", service_text)

        deployment_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 18,
                "method": "resources/read",
                "params": {"uri": "ce-rise://deployment/artifact-templates"},
            }
        )
        deployment_text = deployment_response[0]["result"]["contents"][0]["text"]
        self.assertIn("compose_baseline_external_adapter", deployment_text)

        examples_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 19,
                "method": "resources/read",
                "params": {"uri": "ce-rise://examples/reference-generalization"},
            }
        )
        examples_text = examples_response[0]["result"]["contents"][0]["text"]
        self.assertIn("dp_system_local_demonstrator", examples_text)

        updates_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "resources/read",
                "params": {"uri": "ce-rise://updates/channels"},
            }
        )
        updates_text = updates_response[0]["result"]["contents"][0]["text"]
        self.assertIn("hex_core_service_codeberg_releases", updates_text)

    def test_adoption_context_assessment_matches_value_chain_concepts(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "assess_adoption_context",
                    "arguments": {
                        "adoption_context": {
                            "organization_role": "component supplier",
                            "passport_scope": "product module",
                            "compliance_drivers": ["customer reporting request"],
                            "value_chain_actors": ["component supplier", "manufacturer", "recycler"],
                            "shared_information": ["material composition", "provenance", "compliance evidence"],
                            "value_goals": ["reduce repeated reporting", "support recycling"],
                        }
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "adoption_context_assessment_result")
        self.assertIn(structured["content"]["context_level"], {"partial", "rich"})
        self.assertGreater(len(structured["content"]["candidate_information_flows"]), 0)
        self.assertGreater(len(structured["content"]["source_references"]), 0)
        self.assertIn("legal compliance certification", structured["diagnostics"][0]["message"])

    def test_value_chain_flow_mapping_returns_reuse_components(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "map_value_chain_flows",
                    "arguments": {
                        "product_scope": "product module",
                        "organization_role": "manufacturer",
                        "value_chain_actors": ["supplier", "customer", "recycler"],
                        "information_needs": ["composition", "lifecycle events", "resource efficiency"],
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "value_chain_flow_mapping_result")
        flow_ids = {item["flow_id"] for item in structured["content"]["flow_map"]}
        self.assertIn("material_and_composition", flow_ids)
        component_ids = {
            item["id"] for item in structured["content"]["suggested_ce_rise_components"]
        }
        self.assertIn("dp_assessment_workbench", component_ids)
        source_ids = {item["id"] for item in structured["content"]["source_references"]}
        self.assertIn("ce_rise_models_index", source_ids)

    def test_roadmap_uses_adoption_path(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "generate_implementation_roadmap",
                    "arguments": {
                        "adoption_path_id": "value_chain_exchange_path",
                        "time_horizon": "first pilot",
                        "adoption_context": {
                            "organization_role": "manufacturer",
                            "passport_scope": "product family",
                            "shared_information": ["supplier composition", "traceability evidence"],
                        },
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "implementation_roadmap_result")
        self.assertEqual(structured["content"]["path"]["id"], "value_chain_exchange_path")
        self.assertGreater(len(structured["content"]["phases"]), 0)
        source_ids = {item["id"] for item in structured["content"]["source_references"]}
        self.assertIn("hex_core_service", source_ids)
        live_service_ids = {item["id"] for item in structured["content"]["live_service_connections"]}
        self.assertIn("hex_core_service_local", live_service_ids)

    def test_connected_sources_report_local_status(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "list_connected_sources",
                    "arguments": {"include_status": True},
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "connected_sources_result")
        source_ids = {item["id"] for item in structured["content"]["sources"]}
        self.assertIn("dp_assessment_workbench", source_ids)
        dpawb = next(item for item in structured["content"]["sources"] if item["id"] == "dp_assessment_workbench")
        self.assertTrue(dpawb["local_status"]["available"])

    def test_connected_source_inspection_reads_curated_headings(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "inspect_connected_source",
                    "arguments": {
                        "source_id": "dp_assessment_workbench",
                        "include_headings": True,
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "connected_source_inspection_result")
        self.assertEqual(structured["content"]["source"]["id"], "dp_assessment_workbench")
        readme = next(item for item in structured["content"]["files"] if item["path"] == "README.md")
        self.assertTrue(readme["exists"])
        self.assertGreater(len(readme["headings"]), 0)

    def test_connected_source_snapshot_links_catalog_component(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "build_connected_solution_snapshot",
                    "arguments": {"source_ids": ["hex_core_service"]},
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "connected_solution_snapshot_result")
        source = structured["content"]["sources"][0]
        self.assertEqual(source["id"], "hex_core_service")
        self.assertEqual(source["catalog_component"]["id"], "hex_core_service")

    def test_deployment_artifact_tools_generate_compose_outputs(self) -> None:
        self.initialize()
        list_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 18,
                "method": "tools/call",
                "params": {
                    "name": "list_deployment_artifact_templates",
                    "arguments": {"target": "compose"},
                },
            }
        )
        list_structured = list_response[0]["result"]["structuredContent"]
        self.assertEqual(list_structured["result_type"], "deployment_artifact_templates_result")
        template_ids = {item["id"] for item in list_structured["content"]["templates"]}
        self.assertIn("compose_baseline_external_adapter", template_ids)

        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 19,
                "method": "tools/call",
                "params": {
                    "name": "generate_deployment_artifacts",
                    "arguments": {
                        "target": "compose",
                        "include_re_indicators": True,
                        "include_internal_adapter": True,
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "deployment_artifact_generation_result")
        files = {item["path"]: item for item in structured["content"]["files"]}
        self.assertIn("compose/docker-compose.yml", files)
        self.assertIn("compose/.env.example", files)
        self.assertIn("compose/registry/catalog.json", files)
        self.assertIn("re-indicators-calculation-service", files["compose/docker-compose.yml"]["content"])
        self.assertIn("io-adapter", files["compose/docker-compose.yml"]["content"])
        source_ids = {item["id"] for item in structured["content"]["source_references"]}
        self.assertIn("dp_system_gitops_template", source_ids)
        self.assertIn(
            "docker compose -f compose/docker-compose.yml --env-file compose/.env.example --profile internal-adapter --profile re-indicators config",
            structured["content"]["validation_commands"],
        )
        self.assertTrue(any("starter artifacts" in item for item in structured["content"]["limitations"]))

    def test_deployment_artifact_tools_generate_kubernetes_outputs(self) -> None:
        self.initialize()
        plan_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "generate_deployment_artifact_plan",
                    "arguments": {
                        "target": "kubernetes",
                        "selected_components": ["hex_core_service", "re_indicators_calculation_service"],
                    },
                },
            }
        )
        plan_structured = plan_response[0]["result"]["structuredContent"]
        self.assertEqual(plan_structured["result_type"], "deployment_artifact_plan_result")
        plan_template_ids = {item["id"] for item in plan_structured["content"]["recommended_templates"]}
        self.assertIn("kubernetes_re_indicators_extension", plan_template_ids)
        self.assertEqual(
            plan_structured["content"]["update_awareness"]["status"],
            "current_metadata_not_checked",
        )

        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {
                    "name": "generate_deployment_artifacts",
                    "arguments": {
                        "target": "kubernetes",
                        "project_name": "Digital Passport Pilot",
                        "include_re_indicators": True,
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "deployment_artifact_generation_result")
        files = {item["path"]: item for item in structured["content"]["files"]}
        self.assertIn("k8s/base/kustomization.yaml", files)
        self.assertIn("k8s/overlays/prod/kustomization.yaml", files)
        self.assertIn("k8s/extensions/re-indicators/kustomization.yaml", files)
        self.assertIn("namespace: digital-passport-pilot-dev", files["k8s/overlays/dev/kustomization.yaml"]["content"])
        self.assertIn(
            "kubectl kustomize k8s/overlays/dev-re-indicators",
            structured["content"]["validation_commands"],
        )

    def test_deployment_generation_can_use_checked_version_context(self) -> None:
        self.initialize()

        def fake_http_request_raw(url: str, method: str, timeout_seconds: float) -> dict[str, object]:
            if "/tags" in url:
                if "re-indicators-specification" in url:
                    body = '[{"name":"pages-v9.9.9","tarball_url":"https://example.test/re.tar.gz","commit":{"sha":"abc"}}]'
                else:
                    body = '[{"name":"pages-v1.2.3","tarball_url":"https://example.test/model.tar.gz","commit":{"sha":"def"}}]'
            else:
                body = (
                    '[{"tag_name":"0.2.0","name":"0.2.0","published_at":"2026-05-01T00:00:00Z",'
                    '"html_url":"https://example.test/release"}]'
                )
            return {
                "url": url,
                "available": True,
                "status": 200,
                "reason": "OK",
                "headers": {
                    "etag": '"abc"',
                    "last_modified": "Wed, 06 May 2026 10:00:00 GMT",
                    "content_type": "application/json",
                },
                "body_text": body,
                "body_bytes": len(body),
                "body_truncated": False,
            }

        with patch("server.mcp_server._http_request_raw", side_effect=fake_http_request_raw):
            response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 23,
                    "method": "tools/call",
                    "params": {
                        "name": "generate_deployment_artifacts",
                        "arguments": {
                            "target": "compose",
                            "include_re_indicators": True,
                            "check_remote_updates": True,
                        },
                    },
                }
            )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "deployment_artifact_generation_result")
        self.assertTrue(structured["content"]["version_context"]["remote_checked"])
        files = {item["path"]: item for item in structured["content"]["files"]}
        self.assertIn("VERSION-CONTEXT.md", files)
        catalog_text = files["compose/registry/catalog.json"]["content"]
        self.assertIn('"model": "re-indicators-specification"', catalog_text)
        self.assertIn('"version": "9.9.9"', catalog_text)
        self.assertIn("pages-v9.9.9/generated/schema.json", catalog_text)
        self.assertIn('"model": "material-profile"', catalog_text)
        self.assertNotIn('"model": "dp-architecture"', catalog_text)
        self.assertNotIn('"model": "template-data-model"', catalog_text)

    def test_deployment_readiness_reports_missing_fields(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 22,
                "method": "tools/call",
                "params": {
                    "name": "assess_deployment_artifact_readiness",
                    "arguments": {
                        "deployment_context": {
                            "target_runtime": "kubernetes",
                            "selected_services": ["hex_core_service"],
                        }
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "deployment_artifact_readiness_result")
        self.assertEqual(structured["content"]["readiness_level"], "early")
        self.assertGreater(structured["content"]["missing_fields"], 0)

    def test_reference_example_generalization_keeps_demo_as_example(self) -> None:
        self.initialize()
        list_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 23,
                "method": "tools/call",
                "params": {
                    "name": "list_reference_examples",
                    "arguments": {"source_component_id": "dp_system_local_demonstrator"},
                },
            }
        )
        list_structured = list_response[0]["result"]["structuredContent"]
        self.assertEqual(list_structured["result_type"], "reference_examples_result")
        example_ids = {item["id"] for item in list_structured["content"]["examples"]}
        self.assertIn("dp_system_local_demonstrator", example_ids)

        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 24,
                "method": "tools/call",
                "params": {
                    "name": "generalize_reference_example",
                    "arguments": {
                        "example_id": "dp_system_local_demonstrator",
                        "target_outcome": "deployment handover planning",
                        "adoption_context": {
                            "organization_role": "manufacturer",
                            "passport_scope": "product family",
                            "value_chain_actors": ["supplier", "customer", "recycler"],
                            "shared_information": ["composition", "traceability evidence"],
                        },
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "reference_example_generalization_result")
        steps = structured["content"]["generalized_steps"]
        self.assertGreater(len(steps), 0)
        first_action = steps[0]["contextualized_action"]
        self.assertIn("product family", first_action)
        all_not_assumptions = [
            assumption
            for step in steps
            for assumption in step["not_assumptions"]
        ]
        self.assertTrue(any("fictional" in assumption for assumption in all_not_assumptions))
        source_ids = {item["id"] for item in structured["content"]["source_references"]}
        self.assertIn("dp_system_local_demonstrator", source_ids)

    def test_update_channel_tools_can_resolve_current_metadata(self) -> None:
        self.initialize()
        list_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 25,
                "method": "tools/call",
                "params": {
                    "name": "list_update_channels",
                    "arguments": {"component_id": "hex_core_service"},
                },
            }
        )
        list_structured = list_response[0]["result"]["structuredContent"]
        self.assertEqual(list_structured["result_type"], "update_channels_result")
        channel_ids = {item["id"] for item in list_structured["content"]["channels"]}
        self.assertIn("hex_core_service_codeberg_releases", channel_ids)

        def fake_http_request_raw(url: str, method: str, timeout_seconds: float) -> dict[str, object]:
            return {
                "url": url,
                "available": True,
                "status": 200,
                "reason": "OK",
                "headers": {
                    "etag": '"abc"',
                    "last_modified": "Wed, 06 May 2026 10:00:00 GMT",
                    "content_type": "application/json",
                },
                "body_text": (
                    '[{"tag_name":"0.1.0","name":"0.1.0","published_at":"2026-05-01T00:00:00Z",'
                    '"html_url":"https://codeberg.org/CE-RISE-software/hex-core-service/releases/tag/0.1.0"}]'
                ),
                "body_bytes": 150,
                "body_truncated": False,
            }

        with patch("server.mcp_server._http_request_raw", side_effect=fake_http_request_raw):
            response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 26,
                    "method": "tools/call",
                    "params": {
                        "name": "check_update_channels",
                        "arguments": {"channel_ids": ["hex_core_service_codeberg_releases"]},
                    },
                }
            )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "update_channel_check_result")
        check = structured["content"]["checks"][0]
        self.assertEqual(check["current"]["latest_version"], "0.1.0")
        self.assertEqual(check["interpretation"]["status"], "current_metadata_available")

    def test_model_update_channels_prefer_published_artifact_tags(self) -> None:
        self.initialize()

        def fake_http_request_raw(url: str, method: str, timeout_seconds: float) -> dict[str, object]:
            body = (
                '[{"name":"v9.9.9","tarball_url":"https://example.test/source.tar.gz"},'
                '{"name":"pages-v1.2.3","tarball_url":"https://example.test/pages.tar.gz"}]'
            )
            return {
                "url": url,
                "available": True,
                "status": 200,
                "reason": "OK",
                "headers": {
                    "etag": '"abc"',
                    "last_modified": "Wed, 06 May 2026 10:00:00 GMT",
                    "content_type": "application/json",
                },
                "body_text": body,
                "body_bytes": len(body),
                "body_truncated": False,
            }

        with patch("server.mcp_server._http_request_raw", side_effect=fake_http_request_raw):
            response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 28,
                    "method": "tools/call",
                    "params": {
                        "name": "check_update_channels",
                        "arguments": {"channel_ids": ["product_profile_tags"]},
                    },
                }
            )
        structured = response[0]["result"]["structuredContent"]
        check = structured["content"]["checks"][0]
        self.assertEqual(check["current"]["latest_version"], "pages-v1.2.3")

    def test_model_repository_discovery_proposes_channels_for_new_models(self) -> None:
        self.initialize()

        def fake_http_request_raw(url: str, method: str, timeout_seconds: float) -> dict[str, object]:
            body = (
                '[{"name":"product-profile","full_name":"CE-RISE-models/product-profile",'
                '"html_url":"https://codeberg.org/CE-RISE-models/product-profile",'
                '"description":"Known model","updated_at":"2026-05-01T00:00:00Z"},'
                '{"name":"new-material-model","full_name":"CE-RISE-models/new-material-model",'
                '"html_url":"https://codeberg.org/CE-RISE-models/new-material-model",'
                '"description":"New model","updated_at":"2026-05-02T00:00:00Z"},'
                '{"name":"new-template","full_name":"CE-RISE-models/new-template",'
                '"html_url":"https://codeberg.org/CE-RISE-models/new-template",'
                '"description":"Project template for data models",'
                '"updated_at":"2026-05-03T00:00:00Z"}]'
            )
            return {
                "url": url,
                "available": True,
                "status": 200,
                "reason": "OK",
                "headers": {
                    "etag": '"abc"',
                    "last_modified": "Wed, 06 May 2026 10:00:00 GMT",
                    "content_type": "application/json",
                },
                "body_text": body,
                "body_bytes": len(body),
                "body_truncated": False,
            }

        with patch("server.mcp_server._http_request_raw", side_effect=fake_http_request_raw):
            response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 29,
                    "method": "tools/call",
                    "params": {
                        "name": "discover_model_repositories",
                        "arguments": {"check_remote": True},
                    },
                }
            )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "model_repository_discovery_result")
        repos = {
            item["name"]: item
            for item in structured["content"]["discovered_repositories"]
        }
        self.assertTrue(repos["product-profile"]["already_configured"])
        self.assertEqual(repos["product-profile"]["known_channel_id"], "product_profile_tags")
        self.assertEqual(
            repos["product-profile"]["candidate_update_channel"]["source_id"],
            "ce_rise_models_index",
        )
        self.assertFalse(repos["new-material-model"]["already_configured"])
        self.assertEqual(
            repos["new-material-model"]["candidate_update_channel"]["id"],
            "new_material_model_tags",
        )
        self.assertEqual(
            repos["new-material-model"]["candidate_update_channel"]["url"],
            "https://codeberg.org/api/v1/repos/CE-RISE-models/new-material-model/tags",
        )
        self.assertTrue(repos["new-material-model"]["artifact_channel_candidate"])
        self.assertEqual(repos["new-template"]["repository_role"], "model_development_template")
        self.assertFalse(repos["new-template"]["artifact_channel_candidate"])
        self.assertEqual(
            repos["new-template"]["candidate_update_channel"]["update_role"],
            "model_template_version",
        )
        self.assertEqual(structured["content"]["new_candidate_count"], 2)
        self.assertEqual(structured["content"]["new_model_artifact_candidate_count"], 1)

    def test_update_aware_context_can_remain_deterministic_without_remote_check(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 27,
                "method": "tools/call",
                "params": {
                    "name": "build_update_aware_solution_context",
                    "arguments": {
                        "component_ids": ["hex_core_service", "ce_rise_models"],
                        "check_remote": False,
                    },
                },
            }
        )
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "update_aware_solution_context_result")
        component_ids = {item["id"] for item in structured["content"]["selected_components"]}
        self.assertIn("hex_core_service", component_ids)
        self.assertEqual(structured["content"]["update_checks"], [])
        channel_ids = {item["id"] for item in structured["content"]["update_channels"]}
        self.assertIn("hex_core_service_codeberg_releases", channel_ids)
        self.assertIn("re_indicators_specification_tags", channel_ids)

    def test_live_service_connection_tools_probe_local_read_only_endpoints(self) -> None:
        self.initialize()

        list_response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {
                    "name": "list_live_service_connections",
                    "arguments": {},
                },
            }
        )
        list_structured = list_response[0]["result"]["structuredContent"]
        self.assertEqual(list_structured["result_type"], "live_service_connections_result")
        service_ids = {item["id"] for item in list_structured["content"]["services"]}
        self.assertIn("hex_core_service_local", service_ids)
        self.assertEqual(
            list_structured["content"]["update_awareness"]["status"],
            "current_metadata_not_checked",
        )

        def fake_http_get(url: str, timeout_seconds: float) -> dict[str, object]:
            if url.endswith("/openapi.json"):
                return {
                    "url": url,
                    "available": True,
                    "status": 200,
                    "reason": "OK",
                    "content_type": "application/json",
                    "body_bytes": 100,
                    "body_truncated": False,
                    "body_kind": "json",
                    "body_summary": {
                        "openapi": "3.1.0",
                        "info": {"type": "object", "keys": ["title", "version"]},
                        "paths": {
                            "count": 2,
                            "methods": {"get": 1, "post": 1},
                            "sample_paths": ["/admin/health", "/records"],
                        },
                    },
                }
            return {
                "url": url,
                "available": True,
                "status": 200,
                "reason": "OK",
                "content_type": "application/json",
                "body_bytes": 20,
                "body_truncated": False,
                "body_kind": "json",
                "body_summary": {"status": "ok"},
            }

        with patch("server.mcp_server._http_get", side_effect=fake_http_get):
            probe_response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 15,
                    "method": "tools/call",
                    "params": {
                        "name": "probe_live_service",
                        "arguments": {
                            "service_id": "hex_core_service_local",
                            "endpoint_ids": ["health", "version"],
                        },
                    },
                }
            )
            openapi_response = self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 16,
                    "method": "tools/call",
                    "params": {
                        "name": "inspect_live_service_openapi",
                        "arguments": {
                            "service_id": "hex_core_service_local",
                        },
                    },
                }
            )
        probe_structured = probe_response[0]["result"]["structuredContent"]
        self.assertEqual(probe_structured["result_type"], "live_service_probe_result")
        self.assertEqual(len(probe_structured["content"]["probes"]), 2)
        self.assertTrue(all(item["response"]["available"] for item in probe_structured["content"]["probes"]))

        openapi_structured = openapi_response[0]["result"]["structuredContent"]
        self.assertEqual(openapi_structured["result_type"], "live_service_openapi_inspection_result")
        response = openapi_structured["content"]["response"]
        self.assertTrue(response["available"])
        self.assertEqual(response["body_summary"]["paths"]["count"], 2)

    def test_live_service_base_url_override_is_localhost_only(self) -> None:
        self.initialize()
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 17,
                "method": "tools/call",
                "params": {
                    "name": "probe_live_service",
                    "arguments": {
                        "service_id": "hex_core_service_local",
                        "base_url": "https://example.com",
                    },
                },
            }
        )
        self.assertTrue(response[0]["result"]["isError"])
        structured = response[0]["result"]["structuredContent"]
        self.assertEqual(structured["result_type"], "error_result")


if __name__ == "__main__":
    unittest.main()
