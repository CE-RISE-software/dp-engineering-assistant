"""Read-only consistency checks on supplied, resolved deployment documents."""

from __future__ import annotations

import base64
import json
import posixpath
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import yaml

SERVICE_TYPES = {
    "hex-core-service": ("core", "SERVER_PORT", 8080),
    "re-indicators-calculation": ("re", "PORT", 8081),
    "see-impacts-calculation": ("see", "PORT", 8080),
}
REQUIRED_MODELS = {
    "re": {"re-indicators-specification"},
    "see": {"product-system", "lci-dataset", "integrated-lca"},
}


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = set()
        for key, _ in node.value:
            if key.tag == "tag:yaml.org,2002:merge":
                continue
            value = self.construct_object(key, deep=deep)
            try:
                if value in keys:
                    raise ValueError("duplicate mapping key")
                keys.add(value)
            except TypeError as error:
                raise ValueError("mapping keys must be scalar values") from error
        return super().construct_mapping(node, deep=deep)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _check_document_graph(value, active=None, seen=None, depth=0):
    if depth > 100:
        raise ValueError("configuration nesting limit exceeded")
    if not isinstance(value, (dict, list)):
        return
    active = set() if active is None else active
    seen = set() if seen is None else seen
    identity = id(value)
    if identity in active:
        raise ValueError("recursive configuration aliases are not supported")
    if identity in seen:
        return
    active.add(identity)
    seen.add(identity)
    if len(seen) > 20_000:
        raise ValueError("configuration node limit exceeded")
    if isinstance(value, dict) and not all(isinstance(key, str) for key in value):
        raise ValueError("configuration keys must be strings")
    for item in value.values() if isinstance(value, dict) else value:
        _check_document_graph(item, active, seen, depth + 1)
    active.remove(identity)


def _service_type(name, image):
    image_name = str(image or "").split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0]
    for component, settings in SERVICE_TYPES.items():
        if image_name == component or (
            (not image or "${" in str(image))
            and (name == component or name == component + "-service")
        ):
            return settings
    return None


def _pod_template(resource):
    kind = resource.get("kind")
    if kind == "Pod":
        return resource
    spec = resource.get("spec")
    if kind in ("Deployment", "StatefulSet", "DaemonSet") and isinstance(spec, dict):
        template = spec.get("template")
        return template if isinstance(template, dict) else {}
    return {}


@dataclass
class _Service:
    name: str
    path: str
    kind: str
    port_key: str
    default_port: int
    environment: dict = field(default_factory=dict)
    unknown_environment: bool = False
    namespace: str = "default"
    pod: str = ""
    host_network: bool = False
    labels: dict = field(default_factory=dict)
    ports: dict = field(default_factory=dict)
    pod_ports: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    catalog: object = None


class _Review:
    def __init__(self, files, target, environment, model_catalog):
        self.target = target
        self.environment = environment
        self.model_catalog = model_catalog
        self.findings = []
        self.unchecked = []
        self.out_of_scope = []
        self.services = []
        self.documents = []
        self.resources = []
        self.files = {}
        if not isinstance(files, list) or not files or len(files) > 100:
            raise ValueError(
                "files must contain between 1 and 100 path/content objects"
            )
        total = 0
        for item in files:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].strip()
            ):
                raise ValueError("each file needs a non-empty path")
            path = posixpath.normpath(item["path"])
            if path in self.files or not isinstance(item.get("content"), str):
                raise ValueError(
                    "file paths must be unique and contents must be strings"
                )
            content = item["content"]
            total += len(content.encode("utf-8"))
            if total > 2_000_000:
                raise ValueError("supplied file contents must not exceed 2 MB in total")
            self.files[path] = content
        for path, content in self.files.items():
            if not path.endswith((".json", ".yaml", ".yml")):
                continue
            try:
                documents = (
                    [json.loads(content, object_pairs_hook=_json_pairs)]
                    if path.endswith(".json")
                    else list(yaml.load_all(content, Loader=_UniqueLoader))
                )
                for index, document in enumerate(documents):
                    if document is not None:
                        _check_document_graph(document)
                        self.documents.append(
                            (f"{path}#document[{index}]", document, path)
                        )
            except (ValueError, yaml.YAMLError, RecursionError):
                self.issue(
                    "error",
                    "invalid_document",
                    path,
                    "The configuration is not valid JSON/YAML or contains duplicate keys.",
                    "Correct its syntax and provide it again.",
                )

    def issue(self, severity, code, path, message, recommendation):
        item = {
            "severity": severity,
            "code": code,
            "path": path,
            "message": message,
            "recommendation": recommendation,
        }
        if item not in self.findings:
            self.findings.append(item)

    def shapes(self, value, path, fields):
        valid = isinstance(value, dict)
        if valid:
            for key, expected in fields.items():
                if key in value and not isinstance(value[key], expected):
                    valid = False
                    path += "." + key
                    break
        if not valid:
            self.issue(
                "error",
                "invalid_configuration_structure",
                path,
                "A configuration field has the wrong mapping, array, or scalar type.",
                "Correct the field type in the resolved configuration.",
            )
        return valid

    def skip(self, path, reason):
        item = {"path": path, "reason": reason}
        if item not in self.unchecked:
            self.unchecked.append(item)

    def exclude(self, path, reason):
        item = {"path": path, "reason": reason}
        if item not in self.out_of_scope:
            self.out_of_scope.append(item)

    def integer(self, value, path, default=None):
        if value is None:
            return default
        if (
            isinstance(value, bool)
            or not re.fullmatch(r"[0-9]+", str(value))
            or int(value) <= 0
        ):
            self.issue(
                "error",
                "invalid_positive_integer",
                path,
                "A positive integer is required.",
                "Set a positive numeric value.",
            )
            return None
        return int(value)

    def env_mapping(self, value, path):
        unknown = False
        if isinstance(value, list):
            result = {}
            for entry in value:
                if not isinstance(entry, str) or "=" not in entry:
                    self.skip(
                        path,
                        "Environment entries without supplied values must be resolved first.",
                    )
                    unknown = True
                    continue
                key, content = entry.split("=", 1)
                result[key] = content
            value = result
        if not isinstance(value, dict):
            self.issue(
                "error",
                "invalid_environment",
                path,
                "The environment must be a mapping or a list of assignments.",
                "Provide resolved environment values.",
            )
            return {}, True
        result = {}
        for key, content in value.items():
            if (
                not isinstance(key, str)
                or content is None
                or isinstance(content, (dict, list))
            ):
                self.skip(path, "An environment key or value could not be resolved.")
                unknown = True
            elif "${" in str(content):
                self.skip(
                    path + "." + key,
                    "An environment variable is unresolved; provide rendered configuration.",
                )
                unknown = True
            else:
                result[key] = str(content)
        return result, unknown

    def secret_values(self, resource, path):
        result = {}
        for key, value in (resource.get("data") or {}).items():
            try:
                result[key] = base64.b64decode(value, validate=True).decode("utf-8")
            except (ValueError, TypeError, UnicodeError):
                self.skip(
                    path,
                    "A Secret value is redacted or not valid base64; its configuration value cannot be checked.",
                )
        result.update(resource.get("stringData") or {})
        return result

    def compose(self):
        published = []
        for path, document, file_path in self.documents:
            if not isinstance(document, dict) or "services" not in document:
                continue
            entries = document["services"]
            if not isinstance(entries, dict):
                self.issue(
                    "error",
                    "invalid_services",
                    path + ".services",
                    "Compose services must be a mapping.",
                    "Correct the services mapping.",
                )
                continue
            for name, config in entries.items():
                if not isinstance(config, dict):
                    if _service_type(name, None):
                        self.issue(
                            "error",
                            "invalid_service",
                            path + ".services",
                            "A service is not a mapping.",
                            "Provide a resolved service definition.",
                        )
                    else:
                        self.exclude(
                            path + ".services." + str(name),
                            "External component; its configuration is not assessed.",
                        )
                    continue
                location = f"{path}.services.{name}"
                settings = _service_type(name, config.get("image"))
                if not settings:
                    self.exclude(
                        location,
                        "Component outside the supported CE-RISE review rules; its own configuration is not assessed.",
                    )
                    self.compose_ports(config, location, published, in_scope=False)
                    continue
                if not self.shapes(config, location, {"ports": list, "volumes": list}):
                    continue
                values, unknown = self.env_mapping(
                    config.get("environment", {}), location + ".environment"
                )
                if config.get("env_file"):
                    self.skip(
                        location + ".env_file",
                        "Render Compose with env_file values expanded before review.",
                    )
                    unknown = True
                node = _Service(
                    name,
                    location,
                    *settings,
                    environment=values,
                    unknown_environment=unknown,
                    raw=config,
                )
                self.services.append(node)
                image = str(config.get("image", ""))
                if "${" in image:
                    self.skip(
                        location + ".image", "Resolve the image variable before review."
                    )
                catalog_file = values.get("REGISTRY_CATALOG_FILE")
                if catalog_file:
                    for volume in config.get("volumes", []):
                        if isinstance(volume, str):
                            parts = volume.split(":")
                            source, target = (
                                parts[:2] if len(parts) >= 2 else (None, None)
                            )
                        elif isinstance(volume, dict):
                            if not self.shapes(
                                volume,
                                location + ".volumes",
                                {"source": str, "target": str},
                            ):
                                continue
                            source, target = volume.get("source"), volume.get("target")
                        else:
                            continue
                        if (
                            target
                            and source
                            and (
                                catalog_file == target
                                or catalog_file.startswith(target.rstrip("/") + "/")
                            )
                        ):
                            relative = catalog_file[len(target) :].lstrip("/")
                            source = posixpath.normpath(
                                posixpath.join(
                                    posixpath.dirname(file_path), source, relative
                                )
                            )
                            for _, data, supplied_path in self.documents:
                                if source == supplied_path:
                                    node.catalog = data
                node.ports = self.compose_ports(config, location, published)

    def compose_ports(self, config, location, published, *, in_scope=True):
        result = {}
        if not isinstance(config.get("ports", []), list):
            return result
        for index, port in enumerate(config.get("ports", [])):
            location_port = f"{location}.ports[{index}]"
            if isinstance(port, (str, int)):
                address = str(port).split("/", 1)
                parts = address[0].rsplit(":", 2)
                target = parts[-1]
                public = parts[-2] if len(parts) >= 2 else None
                host = parts[0].strip("[]") if len(parts) == 3 else "0.0.0.0"
                protocol = address[1] if len(address) == 2 else "tcp"
            elif isinstance(port, dict):
                if not in_scope and any(
                    key in port and not isinstance(port[key], expected)
                    for key, expected in {
                        "target": (int, str),
                        "published": (int, str),
                        "host_ip": str,
                        "protocol": str,
                    }.items()
                ):
                    continue
                if not self.shapes(
                    port,
                    location_port,
                    {
                        "target": (int, str),
                        "published": (int, str),
                        "host_ip": str,
                        "protocol": str,
                    },
                ):
                    continue
                target, public = port.get("target"), port.get("published")
                host, protocol = (
                    port.get("host_ip", "0.0.0.0"),
                    port.get("protocol", "tcp"),
                )
            else:
                if in_scope:
                    self.skip(
                        location_port, "This port declaration could not be interpreted."
                    )
                continue
            if not str(target).isdigit() or (
                public is not None and not str(public).isdigit()
            ):
                if in_scope:
                    self.skip(
                        location_port, "Resolve port variables or ranges before review."
                    )
                continue
            result[location_port] = int(target)
            if public is not None and int(public) != 0:
                for (
                    other_host,
                    other_public,
                    other_protocol,
                    other_path,
                    other_scope,
                ) in published:
                    if (
                        (in_scope or other_scope)
                        and str(public) == other_public
                        and protocol == other_protocol
                        and (
                            host == other_host
                            or host in {"0.0.0.0", "::"}
                            or other_host in {"0.0.0.0", "::"}
                        )
                    ):
                        self.issue(
                            "error",
                            "host_port_collision",
                            location_port if in_scope else other_path,
                            "A supplied CE-RISE service's host binding conflicts with another declared binding.",
                            f"Use a distinct binding for the CE-RISE service; the conflicting declaration is {other_path if in_scope else location_port}.",
                        )
                published.append((host, str(public), protocol, location_port, in_scope))
        return result

    def kubernetes_scope(self, resources):
        relevant = set()
        references = set()
        selectors = []
        for path, resource in resources:
            pod = _pod_template(resource)
            spec = pod.get("spec")
            containers = spec.get("containers", []) if isinstance(spec, dict) else []
            if not isinstance(containers, list):
                containers = []
            selected = [
                item
                for item in containers
                if isinstance(item, dict)
                and _service_type(item.get("name"), item.get("image"))
            ]
            metadata = resource.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            if not selected:
                if containers:
                    continue
                if resource.get("kind") not in (
                    "Deployment",
                    "StatefulSet",
                    "DaemonSet",
                    "Pod",
                ) or not _service_type(metadata.get("name"), None):
                    continue
            relevant.add(path)
            namespace = metadata.get("namespace", "default")
            if not isinstance(namespace, str):
                continue
            pod_metadata = pod.get("metadata")
            labels = (
                pod_metadata.get("labels", {}) if isinstance(pod_metadata, dict) else {}
            )
            if isinstance(labels, dict):
                selectors.append((namespace, labels))
            for container in selected:
                for key in ("envFrom", "env"):
                    entries = container.get(key, [])
                    for entry in entries if isinstance(entries, list) else []:
                        if not isinstance(entry, dict):
                            continue
                        value = entry.get("valueFrom", {}) if key == "env" else entry
                        if not isinstance(value, dict):
                            continue
                        for field_name, kind in (
                            ("configMapRef", "ConfigMap"),
                            ("secretRef", "Secret"),
                            ("configMapKeyRef", "ConfigMap"),
                            ("secretKeyRef", "Secret"),
                        ):
                            reference = value.get(field_name)
                            if isinstance(reference, dict) and isinstance(
                                reference.get("name"), str
                            ):
                                references.add((namespace, kind, reference["name"]))
            for volume in (
                spec.get("volumes", [])
                if isinstance(spec, dict) and isinstance(spec.get("volumes", []), list)
                else []
            ):
                if not isinstance(volume, dict):
                    continue
                for field_name, kind, name_key in (
                    ("configMap", "ConfigMap", "name"),
                    ("secret", "Secret", "secretName"),
                ):
                    reference = volume.get(field_name)
                    if isinstance(reference, dict) and isinstance(
                        reference.get(name_key), str
                    ):
                        references.add((namespace, kind, reference[name_key]))
        selected_resources = []
        for path, resource in resources:
            metadata = resource.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            namespace = metadata.get("namespace", "default")
            kind = resource.get("kind")
            name = metadata.get("name")
            identity = (namespace, kind, name)
            referenced = (
                all(isinstance(item, str) for item in identity)
                and identity in references
            )
            spec = resource.get("spec")
            selector = spec.get("selector") if isinstance(spec, dict) else None
            selected_service = (
                kind == "Service"
                and isinstance(selector, dict)
                and selector
                and any(
                    namespace == candidate_namespace
                    and all(labels.get(key) == value for key, value in selector.items())
                    for candidate_namespace, labels in selectors
                )
            )
            if (
                path in relevant
                or referenced
                or selected_service
                or kind == "Kustomization"
            ):
                selected_resources.append((path, resource))
            else:
                self.exclude(
                    path,
                    "External or unrelated Kubernetes resource; its configuration is not assessed.",
                )
        return selected_resources

    def kubernetes(self):
        for path, document, _ in self.documents:
            if not isinstance(document, dict):
                continue
            if document.get("kind") == "List":
                items = document.get("items", [])
                if not isinstance(items, list):
                    self.issue(
                        "error",
                        "invalid_resource_list",
                        path,
                        "Kubernetes List.items must be an array.",
                        "Supply rendered Kubernetes resources.",
                    )
                    continue
                self.resources.extend(
                    (f"{path}.items[{index}]", item)
                    for index, item in enumerate(items)
                    if isinstance(item, dict)
                )
            elif "kind" in document:
                self.resources.append((path, document))
        self.resources = self.kubernetes_scope(self.resources)
        self.resources = [
            (path, resource)
            for path, resource in self.resources
            if self.shapes(
                resource,
                path,
                {"metadata": dict, "spec": dict, "data": dict, "stringData": dict},
            )
            and self.shapes(resource, path, {"kind": str})
            and self.shapes(
                resource.get("metadata", {}),
                path + ".metadata",
                {"name": str, "namespace": str},
            )
        ]
        references = {}
        for path, resource in self.resources:
            metadata = resource.get("metadata") or {}
            if not isinstance(metadata, dict):
                continue
            key = (
                metadata.get("namespace", "default"),
                resource.get("kind"),
                metadata.get("name"),
            )
            if key in references:
                self.issue(
                    "error",
                    "duplicate_resource",
                    path,
                    "A Kubernetes resource identity is duplicated.",
                    "Render one environment overlay at a time.",
                )
            references[key] = resource
            if resource.get("kind") == "Kustomization":
                self.skip(
                    path,
                    "Run kubectl kustomize first; source overlays are not evaluated by this tool.",
                )
        for path, resource in self.resources:
            kind = resource.get("kind")
            if kind not in {"Deployment", "StatefulSet", "DaemonSet", "Pod"}:
                continue
            metadata = resource.get("metadata") or {}
            spec = resource.get("spec") or {}
            if not self.shapes(spec, path + ".spec", {"template": dict}):
                continue
            pod = resource if kind == "Pod" else spec.get("template", {})
            if not self.shapes(pod, path + ".pod", {"spec": dict, "metadata": dict}):
                continue
            pod_spec = pod.get("spec") or {}
            if not self.shapes(
                pod_spec, path + ".pod.spec", {"containers": list, "volumes": list}
            ):
                continue
            if not self.shapes(
                pod.get("metadata", {}), path + ".pod.metadata", {"labels": dict}
            ):
                continue
            namespace = metadata.get("namespace", "default")
            for index, container in enumerate(pod_spec.get("containers", [])):
                if not self.shapes(
                    container,
                    path + ".containers",
                    {
                        "envFrom": list,
                        "env": list,
                        "ports": list,
                        "volumeMounts": list,
                        "startupProbe": dict,
                        "readinessProbe": dict,
                        "livenessProbe": dict,
                    },
                ):
                    continue
                settings = _service_type(container.get("name"), container.get("image"))
                if not settings:
                    continue
                location = (
                    f"{path}.spec.containers[{index}]"
                    if kind == "Pod"
                    else f"{path}.spec.template.spec.containers[{index}]"
                )
                values = {}
                unknown = False
                for reference in container.get("envFrom", []):
                    if not self.shapes(
                        reference,
                        location + ".envFrom",
                        {"configMapRef": dict, "secretRef": dict, "prefix": str},
                    ):
                        unknown = True
                        continue
                    for field_name, reference_kind in (
                        ("configMapRef", "ConfigMap"),
                        ("secretRef", "Secret"),
                    ):
                        if field_name not in reference:
                            continue
                        ref = reference[field_name]
                        if not self.shapes(
                            ref, location + ".envFrom." + field_name, {"name": str}
                        ):
                            unknown = True
                            continue
                        item = references.get(
                            (namespace, reference_kind, ref.get("name"))
                        )
                        if item is None:
                            self.skip(
                                location + ".envFrom",
                                "A referenced ConfigMap or Secret was not supplied; optional references may also exist in the target cluster.",
                            )
                            unknown = True
                            values.clear()
                            continue
                        contents = (
                            dict(item.get("data") or {})
                            if reference_kind == "ConfigMap"
                            else self.secret_values(item, location + ".envFrom")
                        )
                        prefix = reference.get("prefix", "")
                        values.update(
                            {prefix + key: value for key, value in contents.items()}
                        )
                for entry in container.get("env", []):
                    if (
                        not self.shapes(
                            entry, location + ".env", {"name": str, "valueFrom": dict}
                        )
                        or "name" not in entry
                    ):
                        self.skip(
                            location + ".env",
                            "An environment entry is missing a valid name or value declaration.",
                        )
                        unknown = True
                        continue
                    if "value" in entry:
                        values[entry["name"]] = entry["value"]
                    elif "valueFrom" in entry:
                        ref_value = entry["valueFrom"]
                        resolved = False
                        if not self.shapes(
                            ref_value,
                            location + ".env.valueFrom",
                            {"configMapKeyRef": dict, "secretKeyRef": dict},
                        ):
                            unknown = True
                            continue
                        for field_name, reference_kind in (
                            ("configMapKeyRef", "ConfigMap"),
                            ("secretKeyRef", "Secret"),
                        ):
                            if field_name not in ref_value:
                                continue
                            ref = ref_value[field_name]
                            if not self.shapes(
                                ref,
                                location + ".env.valueFrom." + field_name,
                                {"name": str, "key": str},
                            ):
                                unknown = True
                                continue
                            item = references.get(
                                (namespace, reference_kind, ref.get("name"))
                            )
                            contents = (
                                dict((item or {}).get("data") or {})
                                if reference_kind == "ConfigMap"
                                else self.secret_values(item or {}, location + ".env")
                            )
                            if ref.get("key") in contents:
                                values[entry["name"]] = contents[ref["key"]]
                                resolved = True
                        if not resolved:
                            values.pop(entry["name"], None)
                            self.skip(
                                location + ".env",
                                "An environment valueFrom reference was not supplied or could not be resolved.",
                            )
                            unknown = True
                values, unresolved = self.env_mapping(values, location + ".env")
                node = _Service(
                    container.get("name"),
                    location,
                    *settings,
                    environment=values,
                    unknown_environment=unknown or unresolved,
                    namespace=namespace,
                    pod=path,
                    host_network=pod_spec.get("hostNetwork") is True,
                    labels=(pod.get("metadata") or {}).get("labels", {}),
                    raw=container,
                )
                for sibling in pod_spec.get("containers", []):
                    if not isinstance(sibling, dict) or not isinstance(
                        sibling.get("ports", []), list
                    ):
                        continue
                    for sibling_port in sibling.get("ports", []):
                        if isinstance(sibling_port, dict) and isinstance(
                            sibling_port.get("containerPort"), int
                        ):
                            name = sibling_port.get("name")
                            if isinstance(name, str):
                                node.pod_ports[name] = sibling_port["containerPort"]
                            node.pod_ports[str(sibling_port["containerPort"])] = (
                                sibling_port["containerPort"]
                            )
                for port in container.get("ports", []):
                    if self.shapes(
                        port, location + ".ports", {"name": str, "containerPort": int}
                    ):
                        node.ports[port.get("name", str(port.get("containerPort")))] = (
                            port.get("containerPort")
                        )
                catalog_file = values.get("REGISTRY_CATALOG_FILE")
                if catalog_file:
                    volumes = {
                        item.get("name"): item
                        for item in pod_spec.get("volumes", [])
                        if self.shapes(item, location + ".volumes", {"configMap": dict})
                    }
                    for mount in container.get("volumeMounts", []):
                        if not self.shapes(
                            mount, location + ".volumeMounts", {"mountPath": str}
                        ):
                            continue
                        volume = volumes.get(mount.get("name"), {})
                        ref = volume.get("configMap", {})
                        config = references.get(
                            (namespace, "ConfigMap", ref.get("name"))
                        )
                        mount_path = mount.get("mountPath", "")
                        if not config or not (
                            catalog_file == mount_path
                            or catalog_file.startswith(mount_path.rstrip("/") + "/")
                        ):
                            continue
                        relative = mount.get("subPath") or catalog_file[
                            len(mount_path) :
                        ].lstrip("/")
                        key = next(
                            (
                                item["key"]
                                for item in ref.get("items", [])
                                if item.get("path") == relative
                            ),
                            relative,
                        )
                        content = config.get("data", {}).get(key)
                        if isinstance(content, str):
                            try:
                                node.catalog = json.loads(
                                    content, object_pairs_hook=_json_pairs
                                )
                            except ValueError:
                                self.issue(
                                    "error",
                                    "invalid_catalog",
                                    location + ".volumeMounts",
                                    "The mounted catalog is not valid JSON.",
                                    "Correct the catalog ConfigMap data.",
                                )
                self.services.append(node)

    def listening_port(self, service):
        if service.unknown_environment and service.port_key not in service.environment:
            return None
        port = self.integer(
            service.environment.get(service.port_key),
            service.path + ".environment." + service.port_key,
            service.default_port,
        )
        if port is not None and port > 65535:
            self.issue(
                "error",
                "invalid_port",
                service.path,
                "A service port exceeds the valid TCP port range.",
                "Use a port between 1 and 65535.",
            )
            return None
        return port

    def check_catalog(self, service):
        env = service.environment
        keys = [
            key
            for key in (
                "REGISTRY_CATALOG_JSON",
                "REGISTRY_CATALOG_FILE",
                "REGISTRY_CATALOG_URL",
            )
            if env.get(key)
        ]
        if len(keys) != 1 and not service.unknown_environment:
            self.issue(
                "error",
                "catalog_source_count",
                service.path + ".environment",
                "HEX Core requires exactly one model catalog source.",
                "Set exactly one of REGISTRY_CATALOG_JSON, REGISTRY_CATALOG_FILE, or REGISTRY_CATALOG_URL.",
            )
        catalog = service.catalog
        if env.get("REGISTRY_CATALOG_JSON"):
            try:
                catalog = json.loads(
                    env["REGISTRY_CATALOG_JSON"], object_pairs_hook=_json_pairs
                )
            except ValueError:
                self.issue(
                    "error",
                    "invalid_catalog",
                    service.path + ".environment.REGISTRY_CATALOG_JSON",
                    "The inline catalog is not valid JSON.",
                    "Correct the JSON catalog.",
                )
        if catalog is None:
            catalog = self.model_catalog
        if catalog is None:
            self.skip(
                service.path + ".catalog",
                "The referenced model catalog was not supplied; model registration cannot be checked.",
            )
            return None
        entries = catalog.get("models") if isinstance(catalog, dict) else catalog
        if not isinstance(entries, list):
            self.issue(
                "error",
                "invalid_catalog",
                service.path + ".catalog",
                "The catalog must be an array or an object containing a models array.",
                "Provide the catalog structure accepted by HEX Core.",
            )
            return None
        allowed = {
            host.strip().lower()
            for host in env.get("REGISTRY_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        }
        https = env.get("REGISTRY_REQUIRE_HTTPS", "").lower()
        if not allowed and not service.unknown_environment:
            self.issue(
                "error",
                "missing_artifact_hosts",
                service.path + ".environment.REGISTRY_ALLOWED_HOSTS",
                "No model artifact hosts are allowed.",
                "Declare the artifact hosts used by the catalog.",
            )
        if https not in {"true", "false"} and not service.unknown_environment:
            self.issue(
                "error",
                "missing_https_policy",
                service.path + ".environment.REGISTRY_REQUIRE_HTTPS",
                "The registry HTTPS policy is missing or invalid.",
                "Set REGISTRY_REQUIRE_HTTPS to true or false.",
            )
        models = set()
        identities = set()
        for index, entry in enumerate(entries):
            path = f"{service.path}.catalog.models[{index}]"
            if not isinstance(entry, dict):
                self.issue(
                    "error",
                    "invalid_model_entry",
                    path,
                    "A model catalog entry is not an object.",
                    "Provide model, version, and artifact URLs.",
                )
                continue
            model, version = entry.get("model"), entry.get("version")
            if (
                not isinstance(model, str)
                or not model.strip()
                or not isinstance(version, str)
                or not version.strip()
            ):
                self.skip(
                    path,
                    "Model/version inference from artifact URLs is not evaluated; declare them explicitly for this review.",
                )
                continue
            identity = (model, version)
            if identity in identities:
                self.issue(
                    "error",
                    "duplicate_model_version",
                    path,
                    "A model/version pair appears more than once.",
                    "Keep one catalog entry for each model/version pair.",
                )
            identities.add(identity)
            models.add(model)
            artifacts = [
                entry[key]
                for key in ("schema_url", "shacl_url", "owl_url", "openapi_url")
                if entry.get(key)
            ]
            if not artifacts:
                self.issue(
                    "error",
                    "missing_model_artifacts",
                    path,
                    "The model has no artifact URL.",
                    "Supply at least one generated model artifact URL.",
                )
            for artifact in artifacts:
                try:
                    url = urlsplit(artifact)
                    valid = url.scheme in {"https", "http"} and url.hostname
                except (ValueError, TypeError, AttributeError):
                    valid = False
                if not valid:
                    self.issue(
                        "error",
                        "invalid_artifact_url",
                        path,
                        "A model artifact URL is invalid.",
                        "Use an absolute HTTP(S) artifact URL.",
                    )
                    continue
                if allowed and url.hostname.lower() not in allowed:
                    self.issue(
                        "error",
                        "artifact_host_not_allowed",
                        path,
                        "A model artifact host is not allowed by HEX Core.",
                        "Align the artifact URL and REGISTRY_ALLOWED_HOSTS.",
                    )
                if https == "true" and url.scheme != "https":
                    self.issue(
                        "error",
                        "artifact_https_required",
                        path,
                        "A model artifact URL violates the HTTPS requirement.",
                        "Use HTTPS for the artifact URL.",
                    )
                match = re.search(
                    r"/CE-RISE-models/([^/]+)/raw/tag/pages-v([^/]+)/", url.path
                )
                if match and (match[1] != model or match[2] != version):
                    self.issue(
                        "error",
                        "model_artifact_mismatch",
                        path,
                        "The catalog identity differs from its versioned artifact URL.",
                        "Align the declared model/version with the published artifact tag.",
                    )
        return models

    def check_auth(self, service):
        env = service.environment
        mode = env.get("AUTH_MODE", "jwt_jwks")
        if mode == "none":
            if (
                env.get("AUTH_ALLOW_INSECURE_NONE", "").lower() != "true"
                and not service.unknown_environment
            ):
                self.issue(
                    "error",
                    "insecure_auth_not_enabled",
                    service.path + ".environment.AUTH_ALLOW_INSECURE_NONE",
                    "AUTH_MODE=none requires explicit insecure-mode permission.",
                    "Enable it only for isolated development, or configure authentication.",
                )
            if self.environment == "prod":
                self.issue(
                    "error",
                    "production_auth_disabled",
                    service.path + ".environment.AUTH_MODE",
                    "Authentication is disabled in a production configuration.",
                    "Configure the deployment's authentication provider.",
                )
        elif mode == "jwt_jwks":
            for key in ("AUTH_JWKS_URL", "AUTH_ISSUER", "AUTH_AUDIENCE"):
                if not env.get(key) and not service.unknown_environment:
                    self.issue(
                        "error",
                        "missing_jwt_setting",
                        service.path + ".environment." + key,
                        "A required JWT/JWKS setting is missing.",
                        "Provide this setting through environment configuration or a Secret.",
                    )
        elif mode != "forward_auth":
            self.issue(
                "error",
                "unknown_auth_mode",
                service.path + ".environment.AUTH_MODE",
                "The authentication mode is not supported by HEX Core.",
                "Use jwt_jwks, forward_auth, or explicit local none mode.",
            )

    def check_connection(self, service, catalogs):
        value = service.environment.get("HEX_CORE_BASE_URL")
        if not value:
            if service.unknown_environment:
                self.skip(
                    service.path + ".environment.HEX_CORE_BASE_URL",
                    "The service connection could be supplied by unresolved environment references.",
                )
                return
            value = "http://127.0.0.1:8080"
        try:
            url = urlsplit(value)
            port = url.port or (443 if url.scheme == "https" else 80)
            valid = url.scheme in {"http", "https"} and url.hostname
        except ValueError:
            valid = False
        if not valid:
            self.issue(
                "error",
                "invalid_core_url",
                service.path + ".environment.HEX_CORE_BASE_URL",
                "The HEX Core URL is not an absolute HTTP(S) URL with a valid port.",
                "Configure the chosen validation endpoint address; an external compatible implementation is allowed.",
            )
            return
        cores = [item for item in self.services if item.kind == "core"]
        core = None
        if url.hostname in {"127.0.0.1", "localhost", "::1"}:
            core = next(
                (
                    item
                    for item in cores
                    if self.target == "kubernetes" and item.pod == service.pod
                ),
                None,
            )
            network_mode = str(service.raw.get("network_mode", ""))
            if self.target == "compose" and network_mode.startswith("service:"):
                shared_service = network_mode.removeprefix("service:")
                core = next(
                    (item for item in cores if item.name == shared_service), None
                )
            shared_network = (
                service.host_network
                or network_mode == "host"
                or network_mode.startswith(("service:", "container:"))
            )
            if (
                core is None
                and not shared_network
                and port == self.listening_port(service)
            ):
                self.issue(
                    "error",
                    "container_localhost_core",
                    service.path + ".environment.HEX_CORE_BASE_URL",
                    "The validation URL points to this calculation container's own listening port rather than its validation API endpoint.",
                    "Configure the chosen validation service address, whether CE-RISE or external.",
                )
                return
            if core and self.listening_port(core) not in {None, port}:
                self.issue(
                    "error",
                    "core_connection_port",
                    service.path + ".environment.HEX_CORE_BASE_URL",
                    "The local URL port differs from HEX Core's listening port in this pod.",
                    "Use the configured HEX Core container port.",
                )
        elif self.target == "compose":
            core = next((item for item in cores if item.name == url.hostname), None)
            if core and self.listening_port(core) not in {None, port}:
                self.issue(
                    "error",
                    "core_connection_port",
                    service.path + ".environment.HEX_CORE_BASE_URL",
                    "The URL port differs from HEX Core's configured listening port.",
                    "Use the container-network listening port, not the host-published port.",
                )
        else:
            parts = url.hostname.rstrip(".").split(".")
            namespace = parts[1] if len(parts) > 1 else service.namespace
            cluster_service_name = len(parts) <= 2 or parts[2] == "svc"
            for _, resource in self.resources if cluster_service_name else []:
                metadata = resource.get("metadata") or {}
                if (
                    resource.get("kind") != "Service"
                    or metadata.get("name") != parts[0]
                    or metadata.get("namespace", "default") != namespace
                ):
                    continue
                selector = (resource.get("spec") or {}).get("selector") or {}
                core = next(
                    (
                        item
                        for item in cores
                        if item.namespace == namespace
                        and selector
                        and all(
                            item.labels.get(key) == value
                            for key, value in selector.items()
                        )
                    ),
                    None,
                )
                if core and port not in {
                    item.get("port")
                    for item in resource.get("spec", {}).get("ports", [])
                }:
                    self.issue(
                        "error",
                        "core_connection_port",
                        service.path + ".environment.HEX_CORE_BASE_URL",
                        "The HEX Core URL port is not exposed by its Kubernetes Service.",
                        "Use the Service port configured for HEX Core.",
                    )
                break
        if core is None:
            self.exclude(
                service.path + ".environment.HEX_CORE_BASE_URL",
                "The configured endpoint is outside the supplied CE-RISE configuration. Its implementation and compatibility are not assessed; no local HEX Core component is required by this review.",
            )
            return
        registered = catalogs.get(core.path)
        if registered is not None:
            for model in sorted(REQUIRED_MODELS[service.kind] - registered):
                self.issue(
                    "error",
                    "linked_model_not_registered",
                    core.path + ".catalog",
                    f"The explicitly connected CE-RISE calculation service uses {model}, but the supplied HEX Core catalog does not register it.",
                    "Align this declared CE-RISE connection with the calculation service's model contract. This is not a requirement for unrelated components or architectures.",
                )
        if (
            service.kind == "see"
            and core.environment.get("AUTH_MODE", "jwt_jwks") == "jwt_jwks"
            and not service.environment.get("HEX_CORE_BEARER_TOKEN")
        ):
            if service.unknown_environment:
                self.skip(
                    service.path + ".environment.HEX_CORE_BEARER_TOKEN",
                    "A token for authenticated HEX Core must be provided by the deployment's Secret configuration.",
                )
            else:
                self.issue(
                    "error",
                    "missing_see_core_token",
                    service.path + ".environment.HEX_CORE_BEARER_TOKEN",
                    "SEE has no bearer token for the authenticated HEX Core connection.",
                    "Supply HEX_CORE_BEARER_TOKEN without including its real value in the review request.",
                )

    def check_kubernetes_ports(self):
        for path, resource in self.resources:
            if resource.get("kind") != "Service":
                continue
            metadata = resource.get("metadata") or {}
            namespace = metadata.get("namespace", "default")
            spec = resource.get("spec") or {}
            if not self.shapes(spec, path + ".spec", {"selector": dict, "ports": list}):
                continue
            selector = spec.get("selector") or {}
            if not selector:
                continue
            nodes = [
                item
                for item in self.services
                if item.namespace == namespace
                and all(
                    item.labels.get(key) == value for key, value in selector.items()
                )
            ]
            for pod in dict.fromkeys(node.pod for node in nodes):
                pod_nodes = [node for node in nodes if node.pod == pod]
                for index, port in enumerate(spec.get("ports", [])):
                    if not self.shapes(port, f"{path}.spec.ports[{index}]", {}):
                        continue
                    target = port.get("targetPort", port.get("port"))
                    matches = [
                        node
                        for node in pod_nodes
                        if self.listening_port(node) is None
                        or self.listening_port(node)
                        == (
                            node.ports.get(target)
                            if isinstance(target, str)
                            else target
                        )
                    ]
                    if not matches:
                        matches = [
                            node
                            for node in pod_nodes
                            if (
                                node.pod_ports.get(target)
                                if isinstance(target, str)
                                else target
                            )
                            in node.pod_ports.values()
                        ]
                    if not matches:
                        self.issue(
                            "error",
                            "service_target_port",
                            f"{path}.spec.ports[{index}]",
                            "The Service target does not match the selected CE-RISE container's listening port.",
                            "Align targetPort, named container ports, and the service port setting.",
                        )

    def run(self):
        self.compose() if self.target == "compose" else self.kubernetes()
        if not self.services:
            self.exclude(
                "files",
                "No supported CE-RISE component was supplied. External components do not need to be replaced or supplemented for this review.",
            )
        catalogs = {}
        for service in self.services:
            port = self.listening_port(service)
            for exposed in service.ports.values():
                if port is not None and exposed != port:
                    self.issue(
                        "error",
                        "container_target_port",
                        service.path + ".ports",
                        "A declared container target port differs from the service's listening port.",
                        "Align the port mapping and the service's port environment setting.",
                    )
            if service.kind == "core":
                self.check_auth(service)
                catalogs[service.path] = self.check_catalog(service)
        for service in self.services:
            if service.kind in REQUIRED_MODELS:
                self.check_connection(service, catalogs)
            if self.target == "kubernetes":
                for name in ("startupProbe", "readinessProbe", "livenessProbe"):
                    probe = service.raw.get(name) or {}
                    if not self.shapes(
                        probe,
                        service.path + "." + name,
                        {"httpGet": dict, "tcpSocket": dict},
                    ):
                        continue
                    http = probe.get("httpGet") or probe.get("tcpSocket")
                    if http:
                        probe_port = http.get("port")
                        actual = (
                            service.pod_ports.get(probe_port)
                            if isinstance(probe_port, str)
                            else probe_port
                        )
                        if (
                            self.listening_port(service) not in {None, actual}
                            and actual not in service.pod_ports.values()
                        ):
                            self.issue(
                                "error",
                                "probe_port_mismatch",
                                service.path + "." + name,
                                "The probe does not address the service's listening port.",
                                "Align the probe port with the container's configured port.",
                            )
        if self.target == "kubernetes":
            self.check_kubernetes_ports()
        errors = sum(item["severity"] == "error" for item in self.findings)
        status = (
            "inconsistent"
            if errors
            else "incomplete"
            if self.unchecked
            else "not_applicable"
            if not self.services
            else "consistent"
        )
        return {
            "status": status,
            "services_reviewed": len(self.services),
            "summary": {
                "errors": errors,
                "warnings": sum(
                    item["severity"] == "warning" for item in self.findings
                ),
                "unchecked": len(self.unchecked),
            },
            "findings": self.findings,
            "unchecked": self.unchecked,
            "out_of_scope": self.out_of_scope,
            "assessment_scope": "supplied_ce_rise_configuration_only",
            "scope_note": "Users may combine CE-RISE and external components and models without adopting a complete CE-RISE stack. Only supplied CE-RISE settings and explicitly connected CE-RISE interfaces are checked. External components are not assessed or treated as missing. Supplied paths are not opened, and no network calls, deployment, or calculation are performed. This report is not an assessment of the complete system.",
        }


def review_configuration(files, target, environment="local", model_catalog=None):
    if target not in {"compose", "kubernetes"}:
        raise ValueError("target must be compose or kubernetes")
    if environment not in {"local", "dev", "prod"}:
        raise ValueError("environment must be local, dev, or prod")
    if model_catalog is not None and not isinstance(model_catalog, (dict, list)):
        raise ValueError("model_catalog must be a JSON object or array")
    return _Review(files, target, environment, model_catalog).run()
