from __future__ import annotations

import unittest
from unittest.mock import patch

import yaml

from server.mcp_server import (
    assess_deployment_artifact_readiness,
    build_update_aware_solution_context,
    generate_deployment_artifact_plan,
    generate_deployment_artifacts,
    generate_implementation_plan,
    generate_implementation_roadmap,
    recommend_adoption_path,
    recommend_passport_architecture,
)


class MixedCompositionTest(unittest.TestCase):
    def test_architecture_and_plan_preserve_mixed_selections(self):
        selected = [
            "supplier-model",
            "see_impacts_calculation_service",
            "external-analysis",
        ]
        architecture = recommend_passport_architecture(
            {
                "use_case": "Environmental footprint workflow",
                "selected_components": selected,
            }
        )["content"]
        plan = generate_implementation_plan(
            {"goal": "Environmental footprint workflow", "known_components": selected}
        )["content"]
        for result in (architecture, plan):
            self.assertEqual(
                [item["id"] for item in result["component_sequence"]], selected
            )
            self.assertEqual(result["selection_basis"], "user_selection")
            self.assertTrue(result["optional_reference_components"])
            external = next(
                item
                for item in result["component_sequence"]
                if item["id"] == "external-analysis"
            )
            self.assertEqual(external["assessment_scope"], "not_assessed")
        self.assertEqual(plan["architecture_pattern"]["role"], "optional_reference")
        self.assertNotIn(
            "hex_core_service",
            {item for step in plan["steps"] for item in step["ce_rise_reuse"]},
        )

    def test_external_only_adoption_and_roadmap_do_not_insert_ce_rise_parts(self):
        context = {
            "passport_scope": "product family",
            "selected_components": ["supplier-model", "external-platform"],
        }
        result = recommend_adoption_path({"adoption_context": context})["content"]
        self.assertEqual(
            [item["id"] for item in result["component_sequence"]],
            context["selected_components"],
        )
        roadmap = generate_implementation_roadmap({"adoption_context": context})[
            "content"
        ]
        self.assertEqual(roadmap["suggested_ce_rise_components"], [])
        self.assertTrue(all(not phase["ce_rise_reuse"] for phase in roadmap["phases"]))
        self.assertEqual(
            [item["id"] for item in roadmap["selected_components"]],
            context["selected_components"],
        )

    def test_update_context_keeps_external_choices_without_creating_channels(self):
        for selected in (["external-platform"], []):
            with (
                self.subTest(selected=selected),
                patch("server.mcp_server._http_request_raw") as network,
            ):
                result = build_update_aware_solution_context(
                    {"component_ids": selected, "check_remote": True}
                )["content"]
                self.assertEqual(
                    [item["id"] for item in result["selected_components"]], selected
                )
                self.assertEqual(result["update_channels"], [])
                network.assert_not_called()

    def test_reference_architecture_remains_available_when_no_selection_given(self):
        result = recommend_passport_architecture({"use_case": "Digital Passport"})[
            "content"
        ]
        self.assertEqual(result["selection_basis"], "optional_reference_pattern")
        self.assertEqual(result["recommended_pattern"]["role"], "optional_reference")
        self.assertTrue(result["component_sequence"])

    def test_standalone_see_generation_uses_only_selected_ce_rise_parts(self):
        arguments = {
            "target": "both",
            "selected_components": [
                "see_impacts_calculation_service",
                "external-validator",
                "external-analysis",
            ],
            "hex_core_base_url": "https://validator.example.org",
        }
        plan = generate_deployment_artifact_plan(arguments)["content"]
        generated = generate_deployment_artifacts(arguments)["content"]
        self.assertEqual(
            plan["service_components"], ["see_impacts_calculation_service"]
        )
        files = {item["path"]: item["content"] for item in generated["files"]}
        document = yaml.safe_load(files["compose/docker-compose.yml"])
        self.assertEqual(set(document["services"]), {"see-impacts-calculation-service"})
        self.assertNotIn(
            "depends_on", document["services"]["see-impacts-calculation-service"]
        )
        self.assertNotIn("compose/registry/catalog.json", files)
        self.assertNotIn("k8s/base/kustomization.yaml", files)
        self.assertFalse(any(path.startswith("k8s/overlays/") for path in files))
        self.assertIn("https://validator.example.org", files["compose/.env.example"])
        self.assertIn(
            "https://validator.example.org",
            files["k8s/extensions/see-impacts/kustomization.yaml"],
        )
        self.assertNotIn("HEX_CORE_IMAGE=", files["compose/.env.example"])
        self.assertNotIn("REGISTRY_CATALOG_FILE=", files["compose/.env.example"])
        self.assertEqual(
            generated["outside_generation_scope"],
            ["external-validator", "external-analysis"],
        )
        self.assertIn(
            "kubectl kustomize k8s/extensions/see-impacts",
            generated["validation_commands"],
        )
        self.assertEqual(set(plan["candidate_files"]) - set(files), set())

    def test_external_only_generation_does_not_add_a_ce_rise_stack(self):
        arguments = {
            "target": "both",
            "selected_components": ["external-platform"],
            "check_remote_updates": True,
        }
        with patch("server.mcp_server._http_request_raw") as network:
            plan = generate_deployment_artifact_plan(arguments)["content"]
            generated = generate_deployment_artifacts(arguments)["content"]
        self.assertEqual(plan["generation_status"], "not_applicable")
        self.assertEqual(plan["candidate_files"], [])
        self.assertEqual(plan["configuration_decisions"], [])
        self.assertEqual(generated["generation_status"], "not_applicable")
        self.assertFalse(generated["version_context"]["remote_checked"])
        self.assertEqual(generated["files"], [])
        self.assertEqual(generated["validation_commands"], [])
        self.assertEqual(generated["outside_generation_scope"], ["external-platform"])
        network.assert_not_called()

    def test_no_explicit_selection_retains_the_optional_gitops_baseline(self):
        result = generate_deployment_artifacts(
            {"target": "compose", "include_see_impacts": True}
        )["content"]
        files = {item["path"]: item["content"] for item in result["files"]}
        self.assertIn(
            "hex-core-service",
            yaml.safe_load(files["compose/docker-compose.yml"])["services"],
        )
        self.assertIn("compose/registry/catalog.json", files)

    def test_deployment_readiness_does_not_require_ce_rise_for_external_system(self):
        result = assess_deployment_artifact_readiness(
            {"deployment_context": {"selected_services": ["external-platform"]}}
        )["content"]
        self.assertEqual(result["readiness_level"], "not_applicable")
        self.assertEqual(result["missing_fields"], 0)
        self.assertTrue(
            all(item["status"] == "not_applicable" for item in result["checklist"])
        )

    def test_standalone_calculator_does_not_require_local_adapter_or_registry_decisions(
        self,
    ):
        result = assess_deployment_artifact_readiness(
            {
                "deployment_context": {
                    "selected_services": ["see_impacts_calculation_service"]
                }
            }
        )["content"]
        checklist = {item["id"]: item["status"] for item in result["checklist"]}
        self.assertEqual(checklist["io_adapter_strategy"], "not_applicable")
        self.assertEqual(checklist["model_registry_strategy"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
