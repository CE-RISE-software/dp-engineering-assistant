from __future__ import annotations

import base64
import copy
import json
import unittest
from unittest.mock import patch

import yaml

from server.configuration_review import review_configuration
from server.mcp_server import McpServer


def catalog():
    return {
        "models": [
            {
                "model": model,
                "version": version,
                "schema_url": f"https://codeberg.org/CE-RISE-models/{model}/raw/tag/pages-v{version}/generated/schema.json",
            }
            for model, version in (
                ("product-system", "0.0.1"),
                ("lci-dataset", "0.0.1"),
                ("integrated-lca", "0.2.0"),
                ("re-indicators-specification", "0.0.5"),
            )
        ]
    }


def compose():
    return {
        "services": {
            "core": {
                "image": "rg.fr-par.scw.cloud/ce-rise-software/hex-core-service:v0.0.9",
                "environment": {
                    "AUTH_MODE": "none",
                    "AUTH_ALLOW_INSECURE_NONE": "true",
                    "SERVER_PORT": "8080",
                    "REGISTRY_CATALOG_JSON": json.dumps(catalog()),
                    "REGISTRY_ALLOWED_HOSTS": "codeberg.org",
                    "REGISTRY_REQUIRE_HTTPS": "true",
                },
                "ports": [{"target": 8080, "published": "8080"}],
            },
            "footprints": {
                "image": "rg.fr-par.scw.cloud/ce-rise-software/see-impacts-calculation:v0.0.1",
                "environment": {"HEX_CORE_BASE_URL": "http://core:8080"},
                "ports": [
                    {"target": 8080, "published": "8084", "host_ip": "127.0.0.1"}
                ],
            },
        }
    }


def kubernetes():
    core = compose()["services"]["core"]
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "core", "namespace": "pilot"},
            "spec": {
                "template": {
                    "metadata": {"labels": {"app": "core"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "hex-core-service",
                                "image": core["image"],
                                "env": [
                                    {"name": key, "value": value}
                                    for key, value in core["environment"].items()
                                ],
                                "ports": [{"name": "http", "containerPort": 8080}],
                                "readinessProbe": {
                                    "httpGet": {"path": "/admin/ready", "port": "http"}
                                },
                            },
                        ]
                    },
                }
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "core", "namespace": "pilot"},
            "spec": {
                "selector": {"app": "core"},
                "ports": [{"port": 8080, "targetPort": "http"}],
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "see", "namespace": "pilot"},
            "spec": {
                "template": {
                    "metadata": {"labels": {"app": "see"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "see-impacts-calculation-service",
                                "image": compose()["services"]["footprints"]["image"],
                                "env": [
                                    {
                                        "name": "HEX_CORE_BASE_URL",
                                        "value": "http://core.pilot.svc.cluster.local:8080",
                                    }
                                ],
                                "ports": [{"containerPort": 8080}],
                                "readinessProbe": {
                                    "httpGet": {"path": "/capabilities", "port": 8080}
                                },
                            },
                        ]
                    },
                }
            },
        },
    ]


class ConfigurationReviewTest(unittest.TestCase):
    def compose_review(self, config=None, **kwargs):
        config = compose() if config is None else config
        return review_configuration(
            [{"path": "compose.json", "content": json.dumps(config)}],
            "compose",
            **kwargs,
        )

    def kube_review(self, resources=None, **kwargs):
        resources = kubernetes() if resources is None else resources
        return review_configuration(
            [{"path": "rendered.yaml", "content": yaml.safe_dump_all(resources)}],
            "kubernetes",
            **kwargs,
        )

    def assert_code(self, report, code):
        self.assertIn(code, {item["code"] for item in report["findings"]}, report)
        self.assertEqual(report["status"], "inconsistent")

    def test_consistent_compose_and_kubernetes(self):
        for report in (self.compose_review(), self.kube_review()):
            self.assertEqual(report["status"], "consistent", report)
            self.assertEqual(report["services_reviewed"], 2)
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["unchecked"], [])

    def test_wrong_container_and_host_ports(self):
        config = compose()
        config["services"]["footprints"]["ports"][0]["target"] = 8081
        self.assert_code(self.compose_review(config), "container_target_port")
        config = compose()
        config["services"]["footprints"]["ports"][0]["published"] = "8080"
        self.assert_code(self.compose_review(config), "host_port_collision")

    def test_host_port_collision_with_non_ce_rise_service(self):
        config = compose()
        config["services"]["other"] = {
            "image": "postgres:17",
            "ports": [{"target": 5432, "published": "8080"}],
        }
        self.assert_code(self.compose_review(config), "host_port_collision")

    def test_external_only_conflicts_do_not_affect_ce_rise_review(self):
        config = compose()
        config["services"]["analytics"] = {
            "image": "vendor/analytics:1",
            "ports": ["9000:9000"],
        }
        config["services"]["reporting"] = {
            "image": "vendor/reporting:1",
            "ports": ["9000:9001"],
        }
        config["services"]["unrelated"] = {
            "image": "vendor/other:1",
            "ports": "outside-review",
        }
        report = self.compose_review(config)
        self.assertEqual(report["status"], "consistent", report)
        self.assertEqual(report["services_reviewed"], 2)
        self.assertGreaterEqual(len(report["out_of_scope"]), 3)

    def test_external_only_configuration_is_not_applicable_not_missing(self):
        report = self.compose_review(
            {
                "services": {
                    "analytics": {"image": "vendor/analytics:1", "ports": ["9000:9000"]}
                }
            }
        )
        self.assertEqual(report["status"], "not_applicable")
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["unchecked"], [])

    def test_standalone_see_does_not_require_a_local_hex_core(self):
        config = compose()
        del config["services"]["core"]
        config["services"]["footprints"]["environment"]["HEX_CORE_BASE_URL"] = (
            "https://validator.example.org"
        )
        report = self.compose_review(config)
        self.assertEqual(report["status"], "consistent", report)
        self.assertEqual(report["services_reviewed"], 1)
        self.assertEqual(report["findings"], [])
        self.assertTrue(report["out_of_scope"])

    def test_shared_namespace_can_use_an_external_local_validation_endpoint(self):
        config = compose()
        del config["services"]["core"]
        config["services"]["footprints"]["network_mode"] = "service:external-validator"
        config["services"]["footprints"]["environment"]["HEX_CORE_BASE_URL"] = (
            "http://localhost:8080"
        )
        config["services"]["external-validator"] = {"image": "vendor/validator:1"}
        report = self.compose_review(config)
        self.assertEqual(report["status"], "consistent", report)
        self.assertTrue(report["out_of_scope"])
        resources = kubernetes()[2:]
        container = resources[0]["spec"]["template"]["spec"]["containers"][0]
        container["env"][0]["value"] = "http://localhost:9000"
        resources[0]["spec"]["template"]["spec"]["containers"].append(
            {
                "name": "external-validator",
                "image": "vendor/validator:1",
                "ports": [{"containerPort": 9000}],
            }
        )
        report = self.kube_review(resources)
        self.assertEqual(report["status"], "consistent", report)
        self.assertTrue(report["out_of_scope"])

    def test_external_model_catalog_is_allowed_without_ce_rise_calculators(self):
        config = compose()
        del config["services"]["footprints"]
        config["services"]["core"]["environment"].update(
            REGISTRY_ALLOWED_HOSTS="models.example.org",
            REGISTRY_CATALOG_JSON=json.dumps(
                {
                    "models": [
                        {
                            "model": "supplier-data",
                            "version": "1.0",
                            "schema_url": "https://models.example.org/schema.json",
                        }
                    ]
                }
            ),
        )
        self.assertEqual(self.compose_review(config)["status"], "consistent")

    def test_external_image_is_not_ce_rise_just_because_of_service_name(self):
        report = self.compose_review(
            {
                "services": {
                    "hex-core-service": {
                        "image": "vendor/custom-validator:1",
                        "environment": {"OTHER_SETTING": "value"},
                    }
                }
            }
        )
        self.assertEqual(report["status"], "not_applicable", report)
        self.assertEqual(report["findings"], [])

    def test_ephemeral_host_ports_do_not_collide(self):
        config = compose()
        for service in config["services"].values():
            service["ports"][0]["published"] = "0"
        self.assertEqual(self.compose_review(config)["status"], "consistent")

    def test_distinct_host_bindings_are_not_collisions(self):
        config = compose()
        config["services"]["core"]["ports"][0].update(host_ip="127.0.0.1")
        config["services"]["footprints"]["ports"][0].update(
            host_ip="127.0.0.2", published="8080"
        )
        self.assertEqual(self.compose_review(config)["status"], "consistent")

    def test_localhost_and_host_port_in_internal_core_url(self):
        for url, code in (
            ("http://localhost:8080", "container_localhost_core"),
            ("http://core:9999", "core_connection_port"),
            ("http://core:invalid", "invalid_core_url"),
        ):
            with self.subTest(url=url):
                config = compose()
                config["services"]["footprints"]["environment"]["HEX_CORE_BASE_URL"] = (
                    url
                )
                self.assert_code(self.compose_review(config), code)

    def test_explicit_ce_rise_model_binding_and_catalog_duplicates(self):
        config = compose()
        entries = catalog()
        entries["models"] = entries["models"][1:]
        config["services"]["core"]["environment"]["REGISTRY_CATALOG_JSON"] = json.dumps(
            entries
        )
        self.assert_code(self.compose_review(config), "linked_model_not_registered")
        entries["models"].append(copy.deepcopy(entries["models"][0]))
        config["services"]["core"]["environment"]["REGISTRY_CATALOG_JSON"] = json.dumps(
            entries
        )
        self.assert_code(self.compose_review(config), "duplicate_model_version")

    def test_registry_url_policy_and_model_artifact_identity(self):
        for key, value, code in (
            ("REGISTRY_ALLOWED_HOSTS", "example.org", "artifact_host_not_allowed"),
            ("REGISTRY_REQUIRE_HTTPS", "", "missing_https_policy"),
        ):
            config = compose()
            config["services"]["core"]["environment"][key] = value
            self.assert_code(self.compose_review(config), code)
        for url, code in (
            ("http://codeberg.org/schema.json", "artifact_https_required"),
            (
                "https://codeberg.org/CE-RISE-models/product-system/raw/tag/pages-v9.9.9/generated/schema.json",
                "model_artifact_mismatch",
            ),
        ):
            config = compose()
            entries = catalog()
            entries["models"][0]["schema_url"] = url
            config["services"]["core"]["environment"]["REGISTRY_CATALOG_JSON"] = (
                json.dumps(entries)
            )
            self.assert_code(self.compose_review(config), code)

    def test_authentication_requirements(self):
        self.assert_code(
            self.compose_review(environment="prod"), "production_auth_disabled"
        )
        config = compose()
        config["services"]["core"]["environment"]["AUTH_ALLOW_INSECURE_NONE"] = "false"
        self.assert_code(self.compose_review(config), "insecure_auth_not_enabled")
        config = compose()
        config["services"]["core"]["environment"].update(
            AUTH_MODE="jwt_jwks",
            AUTH_JWKS_URL="https://id.example/keys",
            AUTH_ISSUER="https://id.example",
            AUTH_AUDIENCE="core",
        )
        self.assert_code(self.compose_review(config), "missing_see_core_token")
        del config["services"]["core"]["environment"]["AUTH_ISSUER"]
        self.assert_code(self.compose_review(config), "missing_jwt_setting")

    def test_secret_values_are_not_returned(self):
        config = compose()
        secret = "not-a-real-token-sensitive-test-marker"
        config["services"]["footprints"]["environment"]["HEX_CORE_BEARER_TOKEN"] = (
            secret
        )
        report = self.compose_review(config)
        self.assertNotIn(secret, json.dumps(report))

    def test_unresolved_configuration_is_incomplete(self):
        config = compose()
        config["services"]["core"]["env_file"] = [".env"]
        config["services"]["footprints"]["environment"]["HEX_CORE_BASE_URL"] = (
            "${CORE_URL}"
        )
        report = self.compose_review(config)
        self.assertEqual(report["status"], "incomplete", report)
        self.assertTrue(report["unchecked"])
        report = review_configuration(
            [
                {
                    "path": "kustomization.yaml",
                    "content": "kind: Kustomization\nresources: [../base]\n",
                }
            ],
            "kubernetes",
        )
        self.assertEqual(report["status"], "incomplete")

    def test_external_endpoint_is_outside_review_and_ce_rise_catalog_can_be_incomplete(
        self,
    ):
        config = compose()
        config["services"]["footprints"]["environment"]["HEX_CORE_BASE_URL"] = (
            "https://core.example.org"
        )
        report = self.compose_review(config)
        self.assertEqual(report["status"], "consistent")
        self.assertTrue(report["out_of_scope"])
        self.assertEqual(report["unchecked"], [])
        config = compose()
        env = config["services"]["core"]["environment"]
        del env["REGISTRY_CATALOG_JSON"]
        env["REGISTRY_CATALOG_FILE"] = "/config/catalog.json"
        self.assertEqual(self.compose_review(config)["status"], "incomplete")
        self.assertEqual(
            self.compose_review(config, model_catalog=catalog())["status"], "consistent"
        )

    def test_supplied_compose_catalog_file_is_resolved_without_disk_access(self):
        config = compose()
        env = config["services"]["core"]["environment"]
        del env["REGISTRY_CATALOG_JSON"]
        env["REGISTRY_CATALOG_FILE"] = "/config/registry/catalog.json"
        config["services"]["core"]["volumes"] = [
            {
                "source": "./registry/catalog.json",
                "target": "/config/registry/catalog.json",
            }
        ]
        files = [
            {"path": "compose/rendered.json", "content": json.dumps(config)},
            {"path": "compose/registry/catalog.json", "content": json.dumps(catalog())},
        ]
        self.assertEqual(review_configuration(files, "compose")["status"], "consistent")

    def test_kubernetes_service_and_probe_ports(self):
        resources = kubernetes()
        resources[1]["spec"]["ports"][0]["targetPort"] = 9999
        self.assert_code(self.kube_review(resources), "service_target_port")
        resources = kubernetes()
        resources[0]["spec"]["template"]["spec"]["containers"][0]["readinessProbe"][
            "httpGet"
        ]["port"] = "missing"
        self.assert_code(self.kube_review(resources), "probe_port_mismatch")
        resources = kubernetes()
        resources[1]["spec"]["ports"][0]["port"] = 9000
        self.assert_code(self.kube_review(resources), "core_connection_port")

    def test_external_fqdn_sharing_local_service_prefix_is_outside_review(self):
        for hostname in (
            "core.pilot.company.example",
            "core.pilot.svc-gateway.example",
        ):
            with self.subTest(hostname=hostname):
                resources = kubernetes()
                resources[2]["spec"]["template"]["spec"]["containers"][0]["env"][0][
                    "value"
                ] = f"https://{hostname}"
                report = self.kube_review(resources)
                self.assertEqual(report["status"], "consistent", report)
                self.assertEqual(report["findings"], [])
                self.assertTrue(report["out_of_scope"])

    def test_kubernetes_service_dns_forms_are_still_checked(self):
        for hostname in (
            "core",
            "core.pilot",
            "core.pilot.svc",
            "core.pilot.svc.cluster.local",
            "core.pilot.svc.company.internal.",
        ):
            with self.subTest(hostname=hostname):
                resources = kubernetes()
                endpoint = resources[2]["spec"]["template"]["spec"]["containers"][0][
                    "env"
                ][0]
                endpoint["value"] = f"http://{hostname}:8080"
                self.assertEqual(self.kube_review(resources)["status"], "consistent")
                endpoint["value"] = f"http://{hostname}:9000"
                self.assert_code(self.kube_review(resources), "core_connection_port")

    def test_unrelated_kubernetes_resources_do_not_create_ce_rise_errors(self):
        resources = kubernetes()
        external = {
            "kind": "Deployment",
            "metadata": {"name": "external", "namespace": "pilot"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "analytics",
                                "image": "vendor/analytics:1",
                                "env": "outside-review",
                            }
                        ]
                    }
                }
            },
        }
        resources.extend([external, copy.deepcopy(external)])
        resources.append(
            {
                "kind": "ConfigMap",
                "metadata": {"name": "unused", "namespace": "pilot"},
                "data": "outside-review",
            }
        )
        report = self.kube_review(resources)
        self.assertEqual(report["status"], "consistent", report)
        self.assertGreaterEqual(len(report["out_of_scope"]), 3)

    def test_kubernetes_secret_references_and_namespaces(self):
        resources = kubernetes()
        container = resources[0]["spec"]["template"]["spec"]["containers"][0]
        container["envFrom"] = [{"secretRef": {"name": "not-supplied"}}]
        self.assertEqual(self.kube_review(resources)["status"], "incomplete")
        resources.append(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "not-supplied", "namespace": "pilot"},
                "stringData": {"EXTRA_SETTING": "redacted"},
            }
        )
        self.assertEqual(self.kube_review(resources)["status"], "consistent")
        resources[-1]["metadata"]["namespace"] = "other"
        self.assertEqual(self.kube_review(resources)["status"], "incomplete")

    def test_shared_pod_uses_localhost_and_distinct_container_ports(self):
        resources = kubernetes()
        see = resources[2]["spec"]["template"]["spec"]["containers"][0]
        see["env"][0]["value"] = "http://localhost:8080"
        see["env"].append({"name": "PORT", "value": "8082"})
        see["ports"][0]["containerPort"] = 8082
        see["readinessProbe"]["httpGet"]["port"] = 8082
        resources[0]["spec"]["template"]["spec"]["containers"].append(see)
        resources.pop()
        self.assertEqual(self.kube_review(resources)["status"], "consistent")
        see["env"][0]["value"] = "http://localhost:9090"
        self.assert_code(self.kube_review(resources), "core_connection_port")

    def test_service_and_probe_can_target_a_declared_proxy_sidecar(self):
        resources = kubernetes()
        spec = resources[0]["spec"]["template"]["spec"]
        spec["containers"].append(
            {
                "name": "proxy",
                "image": "nginx:1.28",
                "ports": [{"name": "proxy", "containerPort": 9000}],
            }
        )
        spec["containers"][0]["readinessProbe"]["httpGet"]["port"] = "proxy"
        resources[1]["spec"]["ports"][0]["targetPort"] = "proxy"
        self.assertEqual(self.kube_review(resources)["status"], "consistent")

    def test_encoded_secret_values_are_resolved_but_not_returned(self):
        resources = kubernetes()
        container = resources[0]["spec"]["template"]["spec"]["containers"][0]
        container["env"] = [
            item for item in container["env"] if item["name"] != "AUTH_MODE"
        ]
        container["envFrom"] = [{"secretRef": {"name": "settings"}}]
        resources.append(
            {
                "kind": "Secret",
                "metadata": {"name": "settings", "namespace": "pilot"},
                "data": {
                    "AUTH_MODE": base64.b64encode(b"none").decode(),
                    "EXTRA_SECRET": base64.b64encode(b"sensitive-marker").decode(),
                },
            }
        )
        report = self.kube_review(resources)
        self.assertEqual(report["status"], "consistent", report)
        self.assertNotIn("sensitive-marker", json.dumps(report))

    def test_mounted_kubernetes_catalog_is_loaded_from_supplied_configmap(self):
        resources = kubernetes()
        spec = resources[0]["spec"]["template"]["spec"]
        container = spec["containers"][0]
        container["env"] = [
            item for item in container["env"] if item["name"] != "REGISTRY_CATALOG_JSON"
        ]
        container["env"].append(
            {"name": "REGISTRY_CATALOG_FILE", "value": "/config/catalog.json"}
        )
        container["volumeMounts"] = [{"name": "registry", "mountPath": "/config"}]
        spec["volumes"] = [{"name": "registry", "configMap": {"name": "catalog"}}]
        resources.append(
            {
                "kind": "ConfigMap",
                "metadata": {"name": "catalog", "namespace": "pilot"},
                "data": {"catalog.json": json.dumps(catalog())},
            }
        )
        self.assertEqual(self.kube_review(resources)["status"], "consistent")

    def test_malformed_nested_configuration_never_passes(self):
        for field, value in (
            ("env", [{}]),
            ("ports", [1]),
            ("envFrom", [1]),
            ("volumeMounts", 1),
        ):
            resources = kubernetes()
            resources[0]["spec"]["template"]["spec"]["containers"][0][field] = value
            self.assertNotEqual(self.kube_review(resources)["status"], "consistent")

    def test_invalid_syntax_duplicates_and_unsafe_yaml_are_reported(self):
        for content in (
            "services: [",
            "services: {}\nservices: {}\n",
            "!!python/object/apply:os.system ['exit 1']",
            "services: &loop {self: *loop}",
        ):
            with self.subTest(content=content):
                report = review_configuration(
                    [{"path": "compose.yaml", "content": content}], "compose"
                )
                self.assert_code(report, "invalid_document")

    def test_mcp_tool_is_registered_and_never_reads_files_or_contacts_services(self):
        server = McpServer()
        server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "review_configuration_consistency",
                "arguments": {
                    "target": "compose",
                    "files": [
                        {
                            "path": "/does/not/exist/compose.json",
                            "content": json.dumps(compose()),
                        }
                    ],
                },
            },
        }
        with (
            patch("server.mcp_server._http_request_raw") as network,
            patch("server.mcp_server._http_get") as get,
        ):
            response = server.handle_message(request)[0]["result"]
        self.assertFalse(response["isError"], response)
        self.assertEqual(
            response["structuredContent"]["result_type"],
            "configuration_consistency_review_result",
        )
        self.assertEqual(
            response["structuredContent"]["content"]["status"], "consistent"
        )
        self.assertNotIn("files", response["structuredContent"]["inputs"])
        network.assert_not_called()
        get.assert_not_called()

    def test_bad_mcp_arguments_are_rejected(self):
        for files, target in (
            ([], "compose"),
            ([{"path": "x.yaml", "content": 12}], "compose"),
            ([{"path": "x.yaml", "content": "{}"}], "both"),
        ):
            with (
                self.subTest(files=files, target=target),
                self.assertRaises(ValueError),
            ):
                review_configuration(files, target)


if __name__ == "__main__":
    unittest.main()
