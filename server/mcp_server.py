from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

__version__ = "0.0.1"

SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]

JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602

ROOT_PATH = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT_PATH / "data" / "solution_catalog.json"
SOURCES_PATH = ROOT_PATH / "data" / "connected_sources.json"
LIVE_SERVICES_PATH = ROOT_PATH / "data" / "live_service_connections.json"
DEPLOYMENT_ARTIFACTS_PATH = ROOT_PATH / "data" / "deployment_artifacts.json"
REFERENCE_EXAMPLES_PATH = ROOT_PATH / "data" / "reference_examples.json"
UPDATE_CHANNELS_PATH = ROOT_PATH / "data" / "update_channels.json"
MAX_HEADING_SCAN_BYTES = 200_000
MAX_HTTP_BODY_BYTES = 1_000_000


class AssistantError(Exception):
    """Base class for deterministic tool-call errors."""

    code = "assistant_error"

    def to_result(self) -> dict[str, object]:
        return {
            "result_type": "error_result",
            "error": {
                "code": self.code,
                "message": str(self),
                "details": [],
            },
        }


class InputError(AssistantError):
    code = "input_error"


def _tool_input_schema(properties: dict[str, dict[str, object]], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _load_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise InputError("The CE-RISE solution catalog is not a JSON object.")
    return payload


def _load_sources() -> dict[str, Any]:
    with SOURCES_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise InputError("The connected sources manifest is not a JSON object.")
    return payload


def _load_live_services() -> dict[str, Any]:
    with LIVE_SERVICES_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise InputError("The live service connections manifest is not a JSON object.")
    return payload


def _load_deployment_artifacts() -> dict[str, Any]:
    with DEPLOYMENT_ARTIFACTS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise InputError("The deployment artifact manifest is not a JSON object.")
    return payload


def _load_reference_examples() -> dict[str, Any]:
    with REFERENCE_EXAMPLES_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise InputError("The reference example manifest is not a JSON object.")
    return payload


def _load_update_channels() -> dict[str, Any]:
    with UPDATE_CHANNELS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise InputError("The update channel manifest is not a JSON object.")
    return payload


def _result(
    result_type: str,
    inputs: dict[str, object],
    content: dict[str, object],
    diagnostics: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "result_type": result_type,
        "inputs": inputs,
        "content": content,
        "diagnostics": diagnostics or [],
    }


def _string_arg(arguments: dict[str, object], name: str, *, required: bool = True) -> str | None:
    value = arguments.get(name)
    if value is None:
        if required:
            raise InputError(f"Tool argument '{name}' is required.")
        return None
    if not isinstance(value, str):
        raise InputError(f"Tool argument '{name}' must be a string.")
    if required and not value.strip():
        raise InputError(f"Tool argument '{name}' must not be empty.")
    return value


def _string_list_arg(arguments: dict[str, object], name: str) -> list[str]:
    value = arguments.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InputError(f"Tool argument '{name}' must be a list of strings when provided.")
    return value


def _object_arg(arguments: dict[str, object], name: str) -> dict[str, object]:
    value = arguments.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InputError(f"Tool argument '{name}' must be an object when provided.")
    return value


def _bool_arg(arguments: dict[str, object], name: str, *, default: bool = False) -> bool:
    value = arguments.get(name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise InputError(f"Tool argument '{name}' must be a boolean when provided.")
    return value


def _tokens(*values: object) -> set[str]:
    text = " ".join(str(value).lower() for value in values if value is not None)
    return {token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", text) if len(token) > 2}


def _score_record(tokens: set[str], record: dict[str, object]) -> int:
    fields = [
        record.get("id"),
        record.get("family"),
        record.get("kind"),
        record.get("title"),
        record.get("name"),
        record.get("description"),
        record.get("direction"),
        " ".join(str(item) for item in record.get("keywords", []) if isinstance(item, str)),
        " ".join(str(item) for item in record.get("best_for", []) if isinstance(item, str)),
        " ".join(str(item) for item in record.get("evidence_needs", []) if isinstance(item, str)),
        " ".join(str(item) for item in record.get("required_information", []) if isinstance(item, str)),
        " ".join(str(item) for item in record.get("phase_ids", []) if isinstance(item, str)),
    ]
    record_tokens = _tokens(*fields)
    return len(tokens & record_tokens)


def _by_id(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(record["id"]): record for record in records if "id" in record}


def _public_capability(capability: dict[str, object]) -> dict[str, object]:
    return {
        "id": capability["id"],
        "family": capability["family"],
        "title": capability["title"],
        "description": capability["description"],
        "related_components": capability.get("related_components", []),
        "mvp_supported": capability.get("mvp_supported", False),
    }


def _public_component(component: dict[str, object]) -> dict[str, object]:
    return {
        "id": component["id"],
        "name": component["name"],
        "kind": component["kind"],
        "repository": component.get("repository"),
        "url": component.get("url"),
        "description": component["description"],
        "assistant_role": component["assistant_role"],
    }


def _public_pattern(pattern: dict[str, object]) -> dict[str, object]:
    return {
        "id": pattern["id"],
        "title": pattern["title"],
        "description": pattern["description"],
        "best_for": pattern.get("best_for", []),
        "component_sequence": pattern.get("component_sequence", []),
    }


def _public_compliance_driver(driver: dict[str, object]) -> dict[str, object]:
    return {
        "id": driver["id"],
        "title": driver["title"],
        "description": driver["description"],
        "evidence_needs": driver.get("evidence_needs", []),
    }


def _public_flow_type(flow_type: dict[str, object]) -> dict[str, object]:
    return {
        "id": flow_type["id"],
        "title": flow_type["title"],
        "description": flow_type["description"],
        "direction": flow_type.get("direction"),
        "related_components": flow_type.get("related_components", []),
    }


def _public_value_opportunity(opportunity: dict[str, object]) -> dict[str, object]:
    return {
        "id": opportunity["id"],
        "title": opportunity["title"],
        "description": opportunity["description"],
        "required_information": opportunity.get("required_information", []),
        "related_components": opportunity.get("related_components", []),
    }


def _public_adoption_path(path: dict[str, object]) -> dict[str, object]:
    return {
        "id": path["id"],
        "title": path["title"],
        "description": path["description"],
        "best_for": path.get("best_for", []),
        "phase_ids": path.get("phase_ids", []),
        "component_sequence": path.get("component_sequence", []),
    }


def _public_deployment_template(template: dict[str, object]) -> dict[str, object]:
    return {
        "id": template["id"],
        "target": template["target"],
        "title": template["title"],
        "description": template["description"],
        "best_for": template.get("best_for", []),
        "included_files": template.get("included_files", []),
        "service_components": template.get("service_components", []),
        "source_files": template.get("source_files", []),
        "assumptions": template.get("assumptions", []),
    }


def _public_reference_example(example: dict[str, object]) -> dict[str, object]:
    return {
        "id": example["id"],
        "title": example["title"],
        "source_component_id": example.get("source_component_id"),
        "source_id": example.get("source_id"),
        "repository_url": example.get("repository_url"),
        "example_role": example["example_role"],
        "concrete_example_elements": example.get("concrete_example_elements", []),
        "pattern_ids": [
            pattern["id"]
            for pattern in example.get("generalizable_patterns", [])
            if isinstance(pattern, dict) and "id" in pattern
        ],
        "reuse_boundaries": example.get("reuse_boundaries", []),
    }


def _public_update_channel(channel: dict[str, object]) -> dict[str, object]:
    return {
        "id": channel["id"],
        "component_id": channel.get("component_id"),
        "source_id": channel.get("source_id"),
        "kind": channel["kind"],
        "title": channel["title"],
        "description": channel["description"],
        "url": channel["url"],
        "update_role": channel.get("update_role"),
    }


def _field_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _flatten_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return "" if value is None else str(value)


def _rank_records(records: list[dict[str, object]], tokens: set[str]) -> list[dict[str, object]]:
    return [
        record
        for score, record in sorted(
            ((_score_record(tokens, record), record) for record in records),
            key=lambda item: (-item[0], str(item[1]["id"])),
        )
        if score > 0
    ]


def _records_by_ids(records: list[dict[str, object]], ids: list[str]) -> list[dict[str, object]]:
    by_id = _by_id(records)
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def _public_source(source: dict[str, object]) -> dict[str, object]:
    return {
        "id": source["id"],
        "component_id": source.get("component_id"),
        "title": source["title"],
        "kind": source["kind"],
        "connection_modes": source.get("connection_modes", []),
        "repository_url": source.get("repository_url"),
        "documentation_url": source.get("documentation_url"),
        "source_role": source["source_role"],
        "key_files": source.get("key_files", []),
    }


def _source_root(source: dict[str, object]) -> Path | None:
    local_path = source.get("local_path")
    if not isinstance(local_path, str) or not local_path:
        return None
    return (ROOT_PATH / local_path).resolve()


def _safe_source_file(source: dict[str, object], relative_path: str) -> Path:
    root = _source_root(source)
    if root is None:
        raise InputError(f"Source '{source.get('id')}' has no local path.")
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise InputError(f"Source file path escapes source root: {relative_path}")
    return candidate


def _local_source_status(source: dict[str, object]) -> dict[str, object]:
    root = _source_root(source)
    if root is None:
        return {
            "mode": "local_repository",
            "available": False,
            "path": None,
            "reason": "No local_path is configured for this source.",
            "key_files": [],
        }
    key_file_status = []
    for relative_path in source.get("key_files", []):
        if not isinstance(relative_path, str):
            continue
        file_path = _safe_source_file(source, relative_path)
        key_file_status.append(
            {
                "path": relative_path,
                "exists": file_path.is_file(),
                "size_bytes": file_path.stat().st_size if file_path.is_file() else None,
            }
        )
    return {
        "mode": "local_repository",
        "available": root.is_dir(),
        "path": str(root),
        "key_files": key_file_status,
    }


def _remote_url_status(url: object, timeout_seconds: float) -> dict[str, object] | None:
    if not isinstance(url, str) or not url:
        return None
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return {
                "url": url,
                "available": 200 <= response.status < 400,
                "status": response.status,
                "reason": response.reason,
            }
    except urllib.error.HTTPError as exc:
        return {
            "url": url,
            "available": False,
            "status": exc.code,
            "reason": exc.reason,
        }
    except Exception as exc:
        return {
            "url": url,
            "available": False,
            "status": None,
            "reason": str(exc),
        }


def _public_live_service(service: dict[str, object]) -> dict[str, object]:
    return {
        "id": service["id"],
        "component_id": service.get("component_id"),
        "title": service["title"],
        "service_family": service["service_family"],
        "default_base_url": service["default_base_url"],
        "source_id": service.get("source_id"),
        "description": service["description"],
        "safe_endpoints": service.get("safe_endpoints", []),
        "blocked_endpoint_patterns": service.get("blocked_endpoint_patterns", []),
    }


def _live_service_by_id(services: list[dict[str, object]], service_id: str) -> dict[str, object]:
    service = next((item for item in services if item.get("id") == service_id), None)
    if service is None:
        raise InputError(f"Unknown service_id: {service_id}")
    return service


def _filter_live_services(services: list[dict[str, object]], service_ids: list[str]) -> list[dict[str, object]]:
    if not service_ids:
        return services
    by_id = _by_id(services)
    unknown = [service_id for service_id in service_ids if service_id not in by_id]
    if unknown:
        raise InputError(f"Unknown service_ids: {', '.join(unknown)}")
    return [by_id[service_id] for service_id in service_ids]


def _endpoint_by_id(service: dict[str, object], endpoint_id: str) -> dict[str, object]:
    endpoint = next(
        (
            item
            for item in service.get("safe_endpoints", [])
            if isinstance(item, dict) and item.get("id") == endpoint_id
        ),
        None,
    )
    if endpoint is None:
        raise InputError(f"Unknown endpoint_id for {service.get('id')}: {endpoint_id}")
    return endpoint


def _safe_base_url(service: dict[str, object], base_url_override: str | None) -> str:
    base_url = base_url_override or str(service["default_base_url"])
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputError(f"Invalid base URL: {base_url}")
    if base_url_override:
        host = parsed.hostname or ""
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise InputError("base_url overrides are restricted to localhost addresses.")
    return base_url.rstrip("/")


def _join_url(base_url: str, path: object) -> str:
    if not isinstance(path, str) or not path.startswith("/"):
        raise InputError(f"Invalid service endpoint path: {path}")
    return base_url.rstrip("/") + path


def _http_get(url: str, timeout_seconds: float) -> dict[str, object]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json, text/plain;q=0.8, */*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read(MAX_HTTP_BODY_BYTES + 1)
            truncated = len(raw_body) > MAX_HTTP_BODY_BYTES
            if truncated:
                raw_body = raw_body[:MAX_HTTP_BODY_BYTES]
            text = raw_body.decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type")
            parsed_body = _parse_http_body(text, content_type)
            return {
                "url": url,
                "available": 200 <= response.status < 400,
                "status": response.status,
                "reason": response.reason,
                "content_type": content_type,
                "body_bytes": len(raw_body),
                "body_truncated": truncated,
                **parsed_body,
            }
    except urllib.error.HTTPError as exc:
        raw_body = exc.read(MAX_HTTP_BODY_BYTES)
        text = raw_body.decode("utf-8", errors="replace")
        return {
            "url": url,
            "available": False,
            "status": exc.code,
            "reason": exc.reason,
            "content_type": exc.headers.get("content-type") if exc.headers else None,
            "body_bytes": len(raw_body),
            "body_truncated": False,
            **_parse_http_body(text, exc.headers.get("content-type") if exc.headers else None),
        }
    except Exception as exc:
        return {
            "url": url,
            "available": False,
            "status": None,
            "reason": str(exc),
            "content_type": None,
            "body_bytes": 0,
            "body_truncated": False,
            "body_kind": "unavailable",
            "body_summary": None,
        }


def _http_request_raw(url: str, method: str, timeout_seconds: float) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method=method,
        headers={"Accept": "application/json, text/plain;q=0.8, */*;q=0.5"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_body = b"" if method == "HEAD" else response.read(MAX_HTTP_BODY_BYTES + 1)
            truncated = len(raw_body) > MAX_HTTP_BODY_BYTES
            if truncated:
                raw_body = raw_body[:MAX_HTTP_BODY_BYTES]
            return {
                "url": url,
                "available": 200 <= response.status < 400,
                "status": response.status,
                "reason": response.reason,
                "headers": {
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "content_type": response.headers.get("content-type"),
                },
                "body_text": raw_body.decode("utf-8", errors="replace"),
                "body_bytes": len(raw_body),
                "body_truncated": truncated,
            }
    except urllib.error.HTTPError as exc:
        raw_body = b"" if method == "HEAD" else exc.read(MAX_HTTP_BODY_BYTES)
        return {
            "url": url,
            "available": False,
            "status": exc.code,
            "reason": exc.reason,
            "headers": {
                "etag": exc.headers.get("etag") if exc.headers else None,
                "last_modified": exc.headers.get("last-modified") if exc.headers else None,
                "content_type": exc.headers.get("content-type") if exc.headers else None,
            },
            "body_text": raw_body.decode("utf-8", errors="replace"),
            "body_bytes": len(raw_body),
            "body_truncated": False,
        }
    except Exception as exc:
        return {
            "url": url,
            "available": False,
            "status": None,
            "reason": str(exc),
            "headers": {
                "etag": None,
                "last_modified": None,
                "content_type": None,
            },
            "body_text": "",
            "body_bytes": 0,
            "body_truncated": False,
        }


def _parse_http_body(text: str, content_type: str | None) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        return {"body_kind": "empty", "body_summary": None}
    if "json" in (content_type or "").lower() or stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stripped)
            return {
                "body_kind": "json",
                "body_summary": _summarize_json(payload),
            }
        except json.JSONDecodeError:
            pass
    return {
        "body_kind": "text",
        "body_summary": stripped[:1000],
    }


def _summarize_json(payload: object) -> object:
    if isinstance(payload, dict):
        summary: dict[str, object] = {}
        for key, value in payload.items():
            if key == "paths" and isinstance(value, dict):
                summary[key] = {
                    "count": len(value),
                    "methods": _openapi_method_counts(value),
                    "sample_paths": list(value.keys())[:20],
                }
            elif key == "components" and isinstance(value, dict):
                summary[key] = {"keys": sorted(value.keys())}
            elif isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
            elif isinstance(value, list):
                summary[key] = {"type": "array", "count": len(value), "sample": value[:5]}
            elif isinstance(value, dict):
                summary[key] = {"type": "object", "keys": sorted(value.keys())[:20]}
            else:
                summary[key] = str(type(value).__name__)
        return summary
    if isinstance(payload, list):
        return {"type": "array", "count": len(payload), "sample": payload[:5]}
    return payload


def _openapi_method_counts(paths: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method in path_item:
            lower = str(method).lower()
            if lower in {"get", "post", "put", "patch", "delete", "options", "head"}:
                counts[lower] = counts.get(lower, 0) + 1
    return counts


def _openapi_summary_from_response(response: dict[str, object]) -> dict[str, object] | None:
    if response.get("body_kind") != "json":
        return None
    summary = response.get("body_summary")
    if not isinstance(summary, dict):
        return None
    paths = summary.get("paths")
    return {
        "title": (summary.get("info") or {}).get("keys") if isinstance(summary.get("info"), dict) else None,
        "openapi": summary.get("openapi"),
        "swagger": summary.get("swagger"),
        "path_summary": paths if isinstance(paths, dict) else None,
    }


def _markdown_headings(path: Path) -> list[dict[str, object]]:
    if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")[:MAX_HEADING_SCAN_BYTES]
    headings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append(
                {
                    "level": len(match.group(1)),
                    "title": match.group(2),
                    "line": line_number,
                }
            )
    return headings


def _source_by_id(sources: list[dict[str, object]], source_id: str) -> dict[str, object]:
    source = next((item for item in sources if item.get("id") == source_id), None)
    if source is None:
        raise InputError(f"Unknown source_id: {source_id}")
    return source


def _filter_sources(sources: list[dict[str, object]], source_ids: list[str]) -> list[dict[str, object]]:
    if not source_ids:
        return sources
    by_id = _by_id(sources)
    unknown = [source_id for source_id in source_ids if source_id not in by_id]
    if unknown:
        raise InputError(f"Unknown source_ids: {', '.join(unknown)}")
    return [by_id[source_id] for source_id in source_ids]


def list_solution_capabilities(arguments: dict[str, object]) -> dict[str, object]:
    family = _string_arg(arguments, "family", required=False)
    catalog = _load_catalog()
    capabilities = catalog["capabilities"]
    if family:
        capabilities = [item for item in capabilities if item.get("family") == family]
    component_ids = _component_ids_from_records(capabilities)
    return _result(
        "solution_capabilities_result",
        {"family": family},
        {
            "catalog_version": catalog["catalog_version"],
            "scope_note": catalog["scope_note"],
            "capabilities": [_public_capability(item) for item in capabilities],
            "update_awareness": _update_awareness_for_components(component_ids),
        },
    )


def list_solution_components(arguments: dict[str, object]) -> dict[str, object]:
    component_kind = _string_arg(arguments, "kind", required=False)
    capability_id = _string_arg(arguments, "capability_id", required=False)
    catalog = _load_catalog()
    components = catalog["components"]
    if component_kind:
        components = [item for item in components if item.get("kind") == component_kind]
    if capability_id:
        capability = next(
            (item for item in catalog["capabilities"] if item.get("id") == capability_id),
            None,
        )
        if capability is None:
            raise InputError(f"Unknown capability_id: {capability_id}")
        component_ids = set(capability.get("related_components", []))
        components = [item for item in components if item.get("id") in component_ids]
    return _result(
        "solution_components_result",
        {"kind": component_kind, "capability_id": capability_id},
        {
            "catalog_version": catalog["catalog_version"],
            "components": [_public_component(item) for item in components],
            "update_awareness": _update_awareness_for_components(
                [str(item["id"]) for item in components if "id" in item]
            ),
        },
    )


def map_user_goal_to_ce_rise_capabilities(arguments: dict[str, object]) -> dict[str, object]:
    user_goal = _string_arg(arguments, "user_goal")
    constraints = _string_list_arg(arguments, "constraints")
    catalog = _load_catalog()
    tokens = _tokens(user_goal, " ".join(constraints))
    scored_capabilities = [
        (_score_record(tokens, capability), capability)
        for capability in catalog["capabilities"]
    ]
    matches = [
        capability
        for score, capability in sorted(scored_capabilities, key=lambda item: (-item[0], str(item[1]["id"])))
        if score > 0
    ]
    if not matches:
        fallback_ids = {"solution_discovery", "implementation_planning"}
        matches = [item for item in catalog["capabilities"] if item["id"] in fallback_ids]
    component_ids: list[str] = []
    for capability in matches:
        for component_id in capability.get("related_components", []):
            if isinstance(component_id, str) and component_id not in component_ids:
                component_ids.append(component_id)
    components = _by_id(catalog["components"])
    suggested_components = [
        _public_component(components[component_id])
        for component_id in component_ids
        if component_id in components
    ]
    return _result(
        "goal_mapping_result",
        {"user_goal": user_goal, "constraints": constraints},
        {
            "matched_capabilities": [_public_capability(item) for item in matches],
            "suggested_components": suggested_components,
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
            "next_questions": [
                "What product, material, or asset scope should the Digital Passport cover?",
                "Which data sources or schemas are already available?",
                "Is this reference-example learning, integration planning, or deployment preparation?"
            ],
        },
        diagnostics=[
            {
                "level": "info",
                "message": "The mapping is deterministic and catalog-based; it does not call live CE-RISE services.",
            }
        ],
    )


def recommend_passport_architecture(arguments: dict[str, object]) -> dict[str, object]:
    use_case = _string_arg(arguments, "use_case")
    priorities = _string_list_arg(arguments, "priorities")
    catalog = _load_catalog()
    tokens = _tokens(use_case, " ".join(priorities))
    patterns = catalog["architecture_patterns"]
    scored_patterns = [
        (_score_record(tokens, pattern), pattern)
        for pattern in patterns
    ]
    recommendations = [
        pattern
        for score, pattern in sorted(scored_patterns, key=lambda item: (-item[0], str(item[1]["id"])))
        if score > 0
    ]
    if not recommendations:
        recommendations = [
            pattern for pattern in patterns if pattern["id"] == "service_backed_passport_system"
        ]
    primary = recommendations[0]
    components = _by_id(catalog["components"])
    sequence = [
        _public_component(components[component_id])
        for component_id in primary.get("component_sequence", [])
        if component_id in components
    ]
    component_ids = _component_ids_from_components(sequence)
    return _result(
        "passport_architecture_recommendation_result",
        {"use_case": use_case, "priorities": priorities},
        {
            "recommended_pattern": _public_pattern(primary),
            "component_sequence": sequence,
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
            "alternatives": [_public_pattern(item) for item in recommendations[1:]],
            "assumptions": [
                "The recommendation is a reuse path through existing CE-RISE assets.",
                "Live service configuration is outside this initial server setup.",
                "The selected path should be checked against project-specific data, governance, and deployment constraints."
            ],
        },
    )


def generate_implementation_plan(arguments: dict[str, object]) -> dict[str, object]:
    goal = _string_arg(arguments, "goal")
    architecture_id = _string_arg(arguments, "architecture_id", required=False)
    known_components = _string_list_arg(arguments, "known_components")
    catalog = _load_catalog()
    pattern = None
    if architecture_id:
        pattern = next(
            (item for item in catalog["architecture_patterns"] if item.get("id") == architecture_id),
            None,
        )
        if pattern is None:
            raise InputError(f"Unknown architecture_id: {architecture_id}")
    else:
        architecture_result = recommend_passport_architecture(
            {"use_case": goal, "priorities": known_components}
        )
        recommended = architecture_result["content"]["recommended_pattern"]
        pattern = next(
            item for item in catalog["architecture_patterns"] if item["id"] == recommended["id"]
        )
    sequence = list(pattern.get("component_sequence", []))
    for component_id in known_components:
        if component_id not in sequence:
            sequence.append(component_id)
    components = _by_id(catalog["components"])
    component_sequence = [
        _public_component(components[component_id])
        for component_id in sequence
        if component_id in components
    ]
    steps = [
        {
            "id": "clarify_scope",
            "title": "Clarify the Digital Passport scope",
            "action": "Declare the product, material, asset, process, or lifecycle slice the passport should cover.",
            "ce_rise_reuse": ["solution_portal"],
        },
        {
            "id": "select_existing_components",
            "title": "Select existing CE-RISE components",
            "action": "Use the recommended component sequence as the initial reuse path and document any project-specific exclusions.",
            "ce_rise_reuse": sequence,
        },
        {
            "id": "choose_data_model_strategy",
            "title": "Choose the data model and validation strategy",
            "action": "Identify available schemas, SHACL assets, or model sources, then assess coverage where possible.",
            "ce_rise_reuse": ["ce_rise_models"],
        },
        {
            "id": "run_local_demonstration",
            "title": "Use the local demonstrator as a reference example",
            "action": "Study or run the local demonstrator to understand how selected CE-RISE components fit together, then generalize the pattern to the declared scope instead of copying the demo data or local-only settings.",
            "ce_rise_reuse": ["dp_system_local_demonstrator"],
        },
        {
            "id": "prepare_deployment_path",
            "title": "Prepare the deployment path",
            "action": "If the local path is stable, map configuration choices to the existing GitOps deployment template.",
            "ce_rise_reuse": ["dp_system_gitops_template"],
        },
        {
            "id": "record_gaps",
            "title": "Record missing information and risks",
            "action": "List missing data sources, model gaps, integration assumptions, deployment constraints, and validation checks.",
            "ce_rise_reuse": ["ce_rise_models"],
        },
    ]
    return _result(
        "implementation_plan_result",
        {
            "goal": goal,
            "architecture_id": architecture_id,
            "known_components": known_components,
        },
        {
            "architecture_pattern": _public_pattern(pattern),
            "component_sequence": component_sequence,
            "source_references": _source_references_for_components(sequence),
            "live_service_connections": _live_service_connections_for_components(sequence),
            "update_awareness": _update_awareness_for_components(sequence),
            "steps": steps,
        },
    )


def assess_implementation_readiness(arguments: dict[str, object]) -> dict[str, object]:
    project_context = _object_arg(arguments, "project_context")
    catalog = _load_catalog()
    checklist = []
    missing = 0
    provided = 0
    for field in catalog["readiness_fields"]:
        field_id = str(field["id"])
        value = project_context.get(field_id)
        is_present = bool(value)
        if is_present:
            provided += 1
        else:
            missing += 1
        checklist.append(
            {
                "id": field_id,
                "label": field["label"],
                "description": field["description"],
                "status": "provided" if is_present else "missing",
            }
        )
    if missing == 0:
        readiness_level = "ready_for_detailed_planning"
    elif provided >= 4:
        readiness_level = "partial"
    else:
        readiness_level = "early"
    return _result(
        "implementation_readiness_result",
        {"project_context": project_context},
        {
            "readiness_level": readiness_level,
            "provided_fields": provided,
            "missing_fields": missing,
            "checklist": checklist,
            "recommended_next_action": _readiness_next_action(readiness_level),
            "update_awareness": _update_awareness_for_components(
                _coerce_string_list(project_context.get("selected_components"))
            ),
        },
    )


def _readiness_next_action(readiness_level: str) -> str:
    if readiness_level == "ready_for_detailed_planning":
        return "Generate an implementation plan and validate component/model choices with the relevant CE-RISE tools."
    if readiness_level == "partial":
        return "Fill the missing readiness fields before treating the plan as implementation-ready."
    return "Start with solution discovery and scope clarification before selecting components."


def assess_adoption_context(arguments: dict[str, object]) -> dict[str, object]:
    adoption_context = _object_arg(arguments, "adoption_context")
    catalog = _load_catalog()
    fields = catalog["adoption_context_fields"]
    checklist = []
    provided = 0
    for field in fields:
        field_id = str(field["id"])
        present = _field_present(adoption_context.get(field_id))
        if present:
            provided += 1
        checklist.append(
            {
                "id": field_id,
                "label": field["label"],
                "description": field["description"],
                "status": "provided" if present else "missing",
            }
        )
    missing_fields = [item for item in checklist if item["status"] == "missing"]
    completeness = provided / len(fields)
    if completeness >= 0.75:
        context_level = "rich"
    elif completeness >= 0.45:
        context_level = "partial"
    else:
        context_level = "early"

    tokens = _tokens(_flatten_text(adoption_context))
    compliance_drivers = _rank_records(catalog["compliance_drivers"], tokens)
    if not compliance_drivers and _field_present(adoption_context.get("compliance_drivers")):
        compliance_drivers = _records_by_ids(
            catalog["compliance_drivers"],
            ["regulatory_reporting", "customer_requirement"],
        )
    flow_types = _rank_records(catalog["value_chain_flow_types"], tokens)
    if not flow_types and _field_present(adoption_context.get("shared_information")):
        flow_types = _records_by_ids(
            catalog["value_chain_flow_types"],
            ["product_identity", "compliance_evidence"],
        )
    opportunities = _rank_records(catalog["value_opportunity_patterns"], tokens)
    if not opportunities and _field_present(adoption_context.get("value_goals")):
        opportunities = _records_by_ids(
            catalog["value_opportunity_patterns"],
            ["reduce_reporting_burden", "improve_supplier_customer_exchange"],
        )
    component_ids = _component_ids_from_records(flow_types + opportunities)

    return _result(
        "adoption_context_assessment_result",
        {"adoption_context": adoption_context},
        {
            "context_level": context_level,
            "provided_fields": provided,
            "missing_fields": len(missing_fields),
            "checklist": checklist,
            "matched_compliance_drivers": [_public_compliance_driver(item) for item in compliance_drivers],
            "candidate_information_flows": [_public_flow_type(item) for item in flow_types],
            "candidate_value_opportunities": [_public_value_opportunity(item) for item in opportunities],
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
            "next_questions": [
                f"Please clarify: {item['label']}"
                for item in missing_fields[:5]
            ],
            "recommended_next_tools": [
                "map_value_chain_flows",
                "identify_value_opportunities",
                "recommend_adoption_path",
                "build_update_aware_solution_context",
            ],
            "compliance_note": catalog["compliance_note"],
        },
        diagnostics=[
            {
                "level": "info",
                "message": "This is a planning assessment, not legal compliance certification.",
            }
        ],
    )


def map_value_chain_flows(arguments: dict[str, object]) -> dict[str, object]:
    adoption_context = _object_arg(arguments, "adoption_context")
    product_scope = _string_arg(arguments, "product_scope", required=False)
    organization_role = _string_arg(arguments, "organization_role", required=False)
    value_chain_actors = _string_list_arg(arguments, "value_chain_actors")
    information_needs = _string_list_arg(arguments, "information_needs")
    catalog = _load_catalog()
    context_role = organization_role or str(adoption_context.get("organization_role") or "declared organization")
    context_scope = product_scope or str(adoption_context.get("passport_scope") or "declared passport scope")
    context_actors = value_chain_actors or _coerce_string_list(adoption_context.get("value_chain_actors"))
    context_information = information_needs or _coerce_string_list(adoption_context.get("shared_information"))
    tokens = _tokens(
        context_role,
        context_scope,
        " ".join(context_actors),
        " ".join(context_information),
        _flatten_text(adoption_context),
    )
    flow_types = _rank_records(catalog["value_chain_flow_types"], tokens)
    if not flow_types:
        flow_types = _records_by_ids(
            catalog["value_chain_flow_types"],
            ["product_identity", "compliance_evidence", "provenance_and_lifecycle_events"],
        )
    flow_map = []
    for flow_type in flow_types:
        flow_map.append(
            {
                "flow_id": flow_type["id"],
                "title": flow_type["title"],
                "information_focus": flow_type["description"],
                "direction": flow_type.get("direction"),
                "source_context": context_role,
                "passport_scope": context_scope,
                "candidate_actors": context_actors,
                "declared_information_needs": context_information,
                "ce_rise_reuse": flow_type.get("related_components", []),
                "questions_to_resolve": [
                    "Who is authoritative for this information?",
                    "Which fields, identifiers, or evidence records are required?",
                    "Which data source currently holds the information?",
                    "How should validation and update responsibility be handled?"
                ],
            }
        )
    component_ids = _component_ids_from_records(flow_types)
    return _result(
        "value_chain_flow_mapping_result",
        {
            "adoption_context": adoption_context,
            "product_scope": product_scope,
            "organization_role": organization_role,
            "value_chain_actors": value_chain_actors,
            "information_needs": information_needs,
        },
        {
            "flow_map": flow_map,
            "suggested_ce_rise_components": _components_from_records(flow_types, catalog),
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
        },
    )


def identify_value_opportunities(arguments: dict[str, object]) -> dict[str, object]:
    adoption_context = _object_arg(arguments, "adoption_context")
    shared_information = _string_list_arg(arguments, "shared_information")
    value_goals = _string_list_arg(arguments, "value_goals")
    selected_flow_ids = _string_list_arg(arguments, "selected_flow_ids")
    catalog = _load_catalog()
    tokens = _tokens(
        " ".join(shared_information),
        " ".join(value_goals),
        " ".join(selected_flow_ids),
        _flatten_text(adoption_context),
    )
    opportunities = _rank_records(catalog["value_opportunity_patterns"], tokens)
    if selected_flow_ids:
        selected_ids = set(selected_flow_ids)
        for opportunity in catalog["value_opportunity_patterns"]:
            required = set(opportunity.get("required_information", []))
            if selected_ids & required and opportunity not in opportunities:
                opportunities.append(opportunity)
    if not opportunities:
        opportunities = _records_by_ids(
            catalog["value_opportunity_patterns"],
            ["reduce_reporting_burden", "improve_internal_data_quality"],
        )
    opportunity_results = []
    declared_information = set(selected_flow_ids)
    for opportunity in opportunities:
        required = [str(item) for item in opportunity.get("required_information", [])]
        opportunity_results.append(
            {
                **_public_value_opportunity(opportunity),
                "declared_information_coverage": [
                    {
                        "information_type": item,
                        "status": "declared" if item in declared_information else "not_yet_declared",
                    }
                    for item in required
                ],
                "next_step": "Map the required information types to concrete fields, sources, owners, and validation checks.",
            }
        )
    component_ids = _component_ids_from_records(opportunities)
    return _result(
        "shared_information_value_opportunities_result",
        {
            "adoption_context": adoption_context,
            "shared_information": shared_information,
            "value_goals": value_goals,
            "selected_flow_ids": selected_flow_ids,
        },
        {
            "opportunities": opportunity_results,
            "suggested_ce_rise_components": _components_from_records(opportunities, catalog),
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
        },
    )


def recommend_adoption_path(arguments: dict[str, object]) -> dict[str, object]:
    adoption_context = _object_arg(arguments, "adoption_context")
    priorities = _string_list_arg(arguments, "priorities")
    catalog = _load_catalog()
    tokens = _tokens(_flatten_text(adoption_context), " ".join(priorities))
    paths = _rank_records(catalog["adoption_paths"], tokens)
    if not paths:
        if _field_present(adoption_context.get("data_sources")) and _field_present(adoption_context.get("shared_information")):
            paths = _records_by_ids(catalog["adoption_paths"], ["local_prototype_path"])
    else:
        paths = _records_by_ids(catalog["adoption_paths"], ["exploration_and_readiness"])
    primary = paths[0]
    component_ids = _component_ids_from_records([primary])
    return _result(
        "adoption_path_recommendation_result",
        {"adoption_context": adoption_context, "priorities": priorities},
        {
            "recommended_path": _public_adoption_path(primary),
            "component_sequence": _component_sequence(primary, catalog),
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
            "alternatives": [_public_adoption_path(item) for item in paths[1:]],
            "phase_outline": [_phase_detail(phase_id) for phase_id in primary.get("phase_ids", [])],
            "assumptions": [
                "The path is a CE-RISE reuse and planning path, not a replacement implementation.",
                "Compliance drivers must be interpreted with qualified legal or domain expertise where required."
            ],
        },
    )


def generate_implementation_roadmap(arguments: dict[str, object]) -> dict[str, object]:
    adoption_context = _object_arg(arguments, "adoption_context")
    adoption_path_id = _string_arg(arguments, "adoption_path_id", required=False)
    time_horizon = _string_arg(arguments, "time_horizon", required=False) or "initial project horizon"
    catalog = _load_catalog()
    if adoption_path_id:
        path = next((item for item in catalog["adoption_paths"] if item.get("id") == adoption_path_id), None)
        if path is None:
            raise InputError(f"Unknown adoption_path_id: {adoption_path_id}")
    else:
        recommendation = recommend_adoption_path({"adoption_context": adoption_context, "priorities": []})
        recommended_id = recommendation["content"]["recommended_path"]["id"]
        path = next(item for item in catalog["adoption_paths"] if item["id"] == recommended_id)

    phases = []
    for index, phase_id in enumerate(path.get("phase_ids", []), start=1):
        detail = _phase_detail(str(phase_id))
        phases.append(
            {
                "sequence": index,
                "id": detail["id"],
                "title": detail["title"],
                "objective": detail["objective"],
                "actions": detail["actions"],
                "ce_rise_reuse": _phase_components(str(phase_id), path),
                "completion_evidence": detail["completion_evidence"],
            }
        )
    component_ids = _component_ids_from_records([path])
    return _result(
        "implementation_roadmap_result",
        {
            "adoption_context": adoption_context,
            "adoption_path_id": adoption_path_id,
            "time_horizon": time_horizon,
        },
        {
            "path": _public_adoption_path(path),
            "time_horizon": time_horizon,
            "phases": phases,
            "suggested_ce_rise_components": _component_sequence(path, catalog),
            "source_references": _source_references_for_components(component_ids),
            "live_service_connections": _live_service_connections_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
            "limitations": [
                "The roadmap is deterministic guidance over the local catalog.",
                "It should be refined against the concrete CE-RISE component documentation before implementation."
            ],
        },
    )


def list_deployment_artifact_templates(arguments: dict[str, object]) -> dict[str, object]:
    target = _deployment_target_arg(arguments, "target", required=False)
    manifest = _load_deployment_artifacts()
    templates = _deployment_templates_for_target(manifest, target)
    component_ids = _unique_strings(
        component
        for template in templates
        for component in template.get("service_components", [])
        if isinstance(component, str)
    )
    component_ids.append(str(manifest["source_component_id"]))
    return _result(
        "deployment_artifact_templates_result",
        {"target": target},
        {
            "manifest_version": manifest["manifest_version"],
            "scope_note": manifest["scope_note"],
            "source_component_id": manifest["source_component_id"],
            "source_repository": manifest["source_repository"],
            "source_reference_files": manifest["source_reference_files"],
            "templates": [_public_deployment_template(item) for item in templates],
            "update_awareness": _update_awareness_for_components(component_ids),
        },
    )


def generate_deployment_artifact_plan(arguments: dict[str, object]) -> dict[str, object]:
    target = _deployment_target_arg(arguments, "target", required=False) or "both"
    adoption_context = _object_arg(arguments, "adoption_context")
    selected_components = _string_list_arg(arguments, "selected_components")
    include_re_indicators = _bool_arg(
        arguments,
        "include_re_indicators",
        default="re_indicators_calculation_service" in selected_components,
    )
    include_internal_adapter = _bool_arg(arguments, "include_internal_adapter", default=False)
    check_remote_updates = _bool_arg(arguments, "check_remote_updates", default=False)
    timeout_seconds = _update_timeout_arg(arguments, "timeout_seconds")
    manifest = _load_deployment_artifacts()
    profile_ids = _deployment_profile_ids(target, include_re_indicators, include_internal_adapter)
    templates = _deployment_templates_by_ids(manifest, profile_ids)
    service_components = _unique_strings(
        component
        for template in templates
        for component in template.get("service_components", [])
        if isinstance(component, str)
    )
    version_component_ids = ["dp_system_gitops_template", "ce_rise_models", *service_components]
    version_context = _version_context_for_components(
        version_component_ids,
        check_remote=check_remote_updates,
        timeout_seconds=timeout_seconds,
    )
    files = _unique_strings(
        file_path
        for template in templates
        for file_path in template.get("included_files", [])
        if isinstance(file_path, str)
    )
    return _result(
        "deployment_artifact_plan_result",
        {
            "target": target,
            "adoption_context": adoption_context,
            "selected_components": selected_components,
            "include_re_indicators": include_re_indicators,
            "include_internal_adapter": include_internal_adapter,
            "check_remote_updates": check_remote_updates,
            "timeout_seconds": timeout_seconds,
        },
        {
            "recommended_templates": [_public_deployment_template(item) for item in templates],
            "service_components": service_components,
            "candidate_files": files,
            "source_references": _source_references_for_components(
                ["dp_system_gitops_template", *service_components]
            ),
            "update_awareness": version_context["update_awareness"],
            "version_context": version_context,
            "configuration_decisions": [
                "Confirm whether HEX Core Service should use an external IO adapter or an internal adapter profile.",
                "Confirm model registry catalog entries and allowed artifact hosts.",
                "Confirm authentication mode and secret management before production use.",
                "Confirm whether the RE Indicators Calculation Service is needed for this workflow.",
                "Run generated artifacts through the canonical template validation commands before deployment.",
            ],
            "next_tools": [
                "generate_deployment_artifacts",
                "assess_deployment_artifact_readiness",
                "inspect_connected_source",
                "build_live_service_readiness_snapshot",
                "build_update_aware_solution_context",
            ],
            "scope_note": manifest["scope_note"],
        },
        diagnostics=[
            {
                "level": "info",
                "message": "The plan maps user choices to starter artifacts derived from the existing CE-RISE GitOps template.",
            }
        ],
    )


def generate_deployment_artifacts(arguments: dict[str, object]) -> dict[str, object]:
    target = _deployment_target_arg(arguments, "target", required=True)
    project_name = _string_arg(arguments, "project_name", required=False) or "ce-rise-dp-system"
    environment = _deployment_environment_arg(arguments, "environment")
    selected_components = _string_list_arg(arguments, "selected_components")
    include_re_indicators = _bool_arg(
        arguments,
        "include_re_indicators",
        default="re_indicators_calculation_service" in selected_components,
    )
    include_internal_adapter = _bool_arg(arguments, "include_internal_adapter", default=False)
    external_io_adapter_url = (
        _string_arg(arguments, "external_io_adapter_url", required=False)
        or "https://io-adapter.example.org"
    )
    auth_mode = _string_arg(arguments, "auth_mode", required=False) or "jwt_jwks"
    manifest = _load_deployment_artifacts()
    profile_ids = _deployment_profile_ids(target, include_re_indicators, include_internal_adapter)
    templates = _deployment_templates_by_ids(manifest, profile_ids)
    service_components = _unique_strings(
        component
        for template in templates
        for component in template.get("service_components", [])
        if isinstance(component, str)
    )
    check_remote_updates = _bool_arg(arguments, "check_remote_updates", default=False)
    timeout_seconds = _update_timeout_arg(arguments, "timeout_seconds")
    version_component_ids = ["dp_system_gitops_template", "ce_rise_models", *service_components]
    version_context = _version_context_for_components(
        version_component_ids,
        check_remote=check_remote_updates,
        timeout_seconds=timeout_seconds,
    )
    files: list[dict[str, object]] = []
    if target in {"compose", "both"}:
        files.extend(
            _generate_compose_artifacts(
                external_io_adapter_url=external_io_adapter_url,
                auth_mode=auth_mode,
                include_re_indicators=include_re_indicators,
                include_internal_adapter=include_internal_adapter,
                version_context=version_context,
            )
        )
    if target in {"kubernetes", "both"}:
        files.extend(
            _generate_kubernetes_artifacts(
                project_name=project_name,
                external_io_adapter_url=external_io_adapter_url,
                include_re_indicators=include_re_indicators,
                version_context=version_context,
            )
        )
    files.append(
        _artifact_file(
            "VERSION-CONTEXT.md",
            _version_context_markdown(version_context),
            "Version context used when generating this starter artifact set.",
            mime_type="text/markdown",
        )
    )
    return _result(
        "deployment_artifact_generation_result",
        {
            "target": target,
            "project_name": project_name,
            "environment": environment,
            "selected_components": selected_components,
            "include_re_indicators": include_re_indicators,
            "include_internal_adapter": include_internal_adapter,
            "external_io_adapter_url": external_io_adapter_url,
            "auth_mode": auth_mode,
            "check_remote_updates": check_remote_updates,
            "timeout_seconds": timeout_seconds,
        },
        {
            "artifact_set_id": f"{_slugify_project_name(project_name)}-{target}-starter",
            "templates": [_public_deployment_template(item) for item in templates],
            "files": files,
            "source_references": _source_references_for_components(
                ["dp_system_gitops_template", *service_components]
            ),
            "update_awareness": version_context["update_awareness"],
            "version_context": version_context,
            "validation_commands": _deployment_validation_commands(
                target,
                include_re_indicators=include_re_indicators,
                include_internal_adapter=include_internal_adapter,
            ),
            "limitations": [
                "Generated files are starter artifacts for planning and review.",
                "The canonical CE-RISE Digital Passport System GitOps Template remains the deployment source of truth.",
                "Secrets, domains, image tags, registry catalog entries, and environment overlays must be checked by the deployment operator.",
            ],
        },
        diagnostics=[
            {
                "level": "info",
                "message": "The server returned file contents only; it did not write deployment artifacts to disk.",
            }
        ],
    )


def assess_deployment_artifact_readiness(arguments: dict[str, object]) -> dict[str, object]:
    deployment_context = _object_arg(arguments, "deployment_context")
    manifest = _load_deployment_artifacts()
    checklist = []
    provided = 0
    for field in manifest["readiness_fields"]:
        field_id = str(field["id"])
        present = _field_present(deployment_context.get(field_id))
        if present:
            provided += 1
        checklist.append(
            {
                "id": field_id,
                "label": field["label"],
                "description": field["description"],
                "status": "provided" if present else "missing",
            }
        )
    missing = len(checklist) - provided
    if missing == 0:
        readiness_level = "ready_for_template_validation"
    elif provided >= 4:
        readiness_level = "partial"
    else:
        readiness_level = "early"
    return _result(
        "deployment_artifact_readiness_result",
        {"deployment_context": deployment_context},
        {
            "readiness_level": readiness_level,
            "provided_fields": provided,
            "missing_fields": missing,
            "checklist": checklist,
            "recommended_next_action": _deployment_readiness_next_action(readiness_level),
            "source_references": _source_references_for_components(["dp_system_gitops_template"]),
            "update_awareness": _update_awareness_for_components(["dp_system_gitops_template"]),
            "scope_note": manifest["scope_note"],
        },
    )


def list_reference_examples(arguments: dict[str, object]) -> dict[str, object]:
    source_component_id = _string_arg(arguments, "source_component_id", required=False)
    manifest = _load_reference_examples()
    examples = manifest["examples"]
    if source_component_id:
        examples = [
            item
            for item in examples
            if item.get("source_component_id") == source_component_id
        ]
    component_ids = _unique_strings(
        str(item.get("source_component_id"))
        for item in examples
        if isinstance(item.get("source_component_id"), str)
    )
    return _result(
        "reference_examples_result",
        {"source_component_id": source_component_id},
        {
            "manifest_version": manifest["manifest_version"],
            "scope_note": manifest["scope_note"],
            "examples": [_public_reference_example(item) for item in examples],
            "update_awareness": _update_awareness_for_components(component_ids),
        },
    )


def generalize_reference_example(arguments: dict[str, object]) -> dict[str, object]:
    example_id = _string_arg(arguments, "example_id")
    adoption_context = _object_arg(arguments, "adoption_context")
    target_outcome = _string_arg(arguments, "target_outcome", required=False) or "general Digital Passport workflow"
    manifest = _load_reference_examples()
    example = _reference_example_by_id(manifest["examples"], example_id)
    scope = str(adoption_context.get("passport_scope") or "the declared passport scope")
    role = str(adoption_context.get("organization_role") or "the adopter")
    actors = _coerce_string_list(adoption_context.get("value_chain_actors"))
    shared_information = _coerce_string_list(adoption_context.get("shared_information"))
    generalized_steps = []
    component_ids: list[str] = []
    for pattern in example.get("generalizable_patterns", []):
        if not isinstance(pattern, dict):
            continue
        assets = [
            item
            for item in pattern.get("reusable_ce_rise_assets", [])
            if isinstance(item, str)
        ]
        component_ids.extend(assets)
        generalized_steps.append(
            {
                "pattern_id": pattern["id"],
                "title": pattern["title"],
                "generalized_action": pattern["generalized_action"],
                "contextualized_action": _contextualize_reference_action(
                    str(pattern["id"]),
                    str(pattern["generalized_action"]),
                    scope=scope,
                    role=role,
                    actors=actors,
                    shared_information=shared_information,
                    target_outcome=target_outcome,
                ),
                "reusable_ce_rise_assets": assets,
                "not_assumptions": pattern.get("not_assumptions", []),
            }
        )
    component_ids.append(str(example.get("source_component_id")))
    component_ids = _unique_strings(component_ids)
    return _result(
        "reference_example_generalization_result",
        {
            "example_id": example_id,
            "adoption_context": adoption_context,
            "target_outcome": target_outcome,
        },
        {
            "reference_example": _public_reference_example(example),
            "target_outcome": target_outcome,
            "generalized_steps": generalized_steps,
            "adaptation_questions": example.get("adaptation_questions", []),
            "reuse_boundaries": example.get("reuse_boundaries", []),
            "source_references": _source_references_for_components(component_ids),
            "update_awareness": _update_awareness_for_components(component_ids),
            "next_tools": [
                "map_value_chain_flows",
                "assess_implementation_readiness",
                "generate_deployment_artifact_plan",
                "inspect_connected_source",
                "build_update_aware_solution_context",
            ],
        },
        diagnostics=[
            {
                "level": "info",
                "message": "The output generalizes reusable patterns from a reference example; it does not prescribe the example's concrete product, payload, auth, or deployment settings.",
            }
        ],
    )


def _reference_example_by_id(
    examples: list[dict[str, object]],
    example_id: str,
) -> dict[str, object]:
    example = next((item for item in examples if item.get("id") == example_id), None)
    if example is None:
        raise InputError(f"Unknown example_id: {example_id}")
    return example


def _contextualize_reference_action(
    pattern_id: str,
    generalized_action: str,
    *,
    scope: str,
    role: str,
    actors: list[str],
    shared_information: list[str],
    target_outcome: str,
) -> str:
    actor_text = ", ".join(actors) if actors else "the relevant value-chain actors"
    information_text = ", ".join(shared_information) if shared_information else "the required shared information"
    if pattern_id == "declare_scope_and_roles":
        return f"For {role}, define {scope}, the actors involved ({actor_text}), and the intended outcome: {target_outcome}."
    if pattern_id == "select_services_and_storage":
        return f"For {scope}, decide which CE-RISE services are needed now and which storage decision is appropriate for {role}."
    if pattern_id == "adapt_model_registry":
        return f"For {scope}, map {information_text} to the CE-RISE model artifacts and registry catalog entries needed for validation."
    if pattern_id == "prepare_representative_payloads":
        return f"Prepare adopter-specific valid, invalid, and edge-case payloads for {scope}; do not reuse the demonstrator's fictional data as evidence."
    if pattern_id == "exercise_lifecycle_operations":
        return f"Choose the lifecycle operations needed for {scope}, such as validation, creation, persistence, query, update, sharing, or read-back."
    if pattern_id == "turn_demo_checks_into_operational_checks":
        return f"Turn the demonstrator's local checks into checks for {target_outcome}, including readiness, validation, service reachability, and deployment-specific controls."
    return generalized_action


def list_update_channels(arguments: dict[str, object]) -> dict[str, object]:
    component_id = _string_arg(arguments, "component_id", required=False)
    source_id = _string_arg(arguments, "source_id", required=False)
    update_role = _string_arg(arguments, "update_role", required=False)
    manifest = _load_update_channels()
    channels = _filter_update_channels(
        manifest["channels"],
        component_id=component_id,
        source_id=source_id,
        update_role=update_role,
    )
    return _result(
        "update_channels_result",
        {
            "component_id": component_id,
            "source_id": source_id,
            "update_role": update_role,
        },
        {
            "manifest_version": manifest["manifest_version"],
            "scope_note": manifest["scope_note"],
            "policy": manifest["policy"],
            "channels": [_public_update_channel(channel) for channel in channels],
        },
    )


def check_update_channels(arguments: dict[str, object]) -> dict[str, object]:
    channel_ids = _string_list_arg(arguments, "channel_ids")
    component_ids = _string_list_arg(arguments, "component_ids")
    timeout_seconds = _update_timeout_arg(arguments, "timeout_seconds")
    manifest = _load_update_channels()
    channels = _select_update_channels(
        manifest["channels"],
        channel_ids=channel_ids,
        component_ids=component_ids,
    )
    checks = [_check_update_channel(channel, timeout_seconds) for channel in channels]
    return _result(
        "update_channel_check_result",
        {
            "channel_ids": channel_ids,
            "component_ids": component_ids,
            "timeout_seconds": timeout_seconds,
        },
        {
            "manifest_version": manifest["manifest_version"],
            "scope_note": manifest["scope_note"],
            "policy": manifest["policy"],
            "checks": checks,
        },
        diagnostics=[
            {
                "level": "info",
                "message": "Update checks are read-only and use only configured HTTP(S) channels.",
            }
        ],
    )


def build_update_aware_solution_context(arguments: dict[str, object]) -> dict[str, object]:
    user_goal = _string_arg(arguments, "user_goal", required=False)
    component_ids = _string_list_arg(arguments, "component_ids")
    check_remote = _bool_arg(arguments, "check_remote", default=False)
    timeout_seconds = _update_timeout_arg(arguments, "timeout_seconds")
    catalog = _load_catalog()
    manifest = _load_update_channels()
    selected_component_ids = component_ids or _component_ids_for_goal(user_goal, catalog)
    components = _components_by_ids(selected_component_ids, catalog)
    channels = _select_update_channels(
        manifest["channels"],
        channel_ids=[],
        component_ids=selected_component_ids,
    )
    update_checks = [_check_update_channel(channel, timeout_seconds) for channel in channels] if check_remote else []
    return _result(
        "update_aware_solution_context_result",
        {
            "user_goal": user_goal,
            "component_ids": component_ids,
            "check_remote": check_remote,
            "timeout_seconds": timeout_seconds,
        },
        {
            "stable_scope_note": catalog["scope_note"],
            "update_policy": manifest["policy"],
            "selected_components": components,
            "update_channels": [_public_update_channel(channel) for channel in channels],
            "update_checks": update_checks,
            "usage_guidance": [
                "Use stable catalog guidance for architecture, scope, and non-substitution rules.",
                "Use update checks for current release, tag, documentation, and artifact metadata.",
                "If remote metadata indicates a newer upstream component, inspect the component documentation before changing implementation guidance.",
            ],
        },
        diagnostics=[
            {
                "level": "info",
                "message": "Remote checks are optional. Pass check_remote=true when current upstream metadata is needed.",
            }
        ] if not check_remote else [],
    )


def discover_model_repositories(arguments: dict[str, object]) -> dict[str, object]:
    check_remote = _bool_arg(arguments, "check_remote", default=True)
    timeout_seconds = _update_timeout_arg(arguments, "timeout_seconds")
    manifest = _load_update_channels()
    channel = _update_channel_by_id(manifest["channels"], "ce_rise_models_codeberg_repositories")
    known_model_channels = [
        _public_update_channel(item)
        for item in manifest["channels"]
        if item.get("component_id") == "ce_rise_models"
        and item.get("update_role") == "model_artifact_version"
    ]
    checks = []
    discovered_repositories: list[dict[str, object]] = []
    if check_remote:
        check = _check_update_channel(channel, timeout_seconds)
        checks.append(check)
        repositories = check.get("current", {}).get("repositories") if isinstance(check.get("current"), dict) else []
        if isinstance(repositories, list):
            discovered_repositories = [
                _model_repository_discovery_item(repo, manifest["channels"])
                for repo in repositories
                if isinstance(repo, dict) and isinstance(repo.get("name"), str)
            ]
    return _result(
        "model_repository_discovery_result",
        {
            "check_remote": check_remote,
            "timeout_seconds": timeout_seconds,
        },
        {
            "discovery_channel": _public_update_channel(channel),
            "known_model_update_channels": known_model_channels,
            "checks": checks,
            "discovered_repositories": discovered_repositories,
            "new_candidate_count": sum(
                1 for item in discovered_repositories if not item.get("already_configured")
            ),
            "new_model_artifact_candidate_count": sum(
                1
                for item in discovered_repositories
                if not item.get("already_configured") and item.get("artifact_channel_candidate")
            ),
            "next_use": [
                "Use candidate_update_channel entries to add explicit update channels when a new model repository should be tracked.",
                "Generated artifacts can use checked model tags only after a repository has an explicit model_artifact_version channel.",
            ],
        },
        diagnostics=[] if check_remote else [
            {
                "level": "info",
                "message": "Remote discovery was not performed. Pass check_remote=true to list current CE-RISE-models repositories.",
            }
        ],
    )


def _update_channel_by_id(
    channels: list[dict[str, object]],
    channel_id: str,
) -> dict[str, object]:
    channel = next((item for item in channels if item.get("id") == channel_id), None)
    if channel is None:
        raise InputError(f"Unknown update channel id: {channel_id}")
    return channel


def _model_repository_discovery_item(
    repo: dict[str, object],
    channels: list[dict[str, object]],
) -> dict[str, object]:
    name = str(repo["name"])
    tag_url = f"https://codeberg.org/api/v1/repos/CE-RISE-models/{name}/tags"
    known = next((channel for channel in channels if channel.get("url") == tag_url), None)
    candidate_id = _model_channel_id(name)
    role = _model_repository_role(repo)
    update_channel = _public_update_channel(known) if isinstance(known, dict) else {
        "id": candidate_id,
        "component_id": "ce_rise_models",
        "source_id": "ce_rise_models_index",
        "kind": "gitea_tags",
        "url": tag_url,
        "title": f"{name} model tags",
        "description": f"Current version tags for the CE-RISE {name} model repository.",
        "update_role": role["candidate_update_role"],
    }
    return {
        "name": name,
        "full_name": repo.get("full_name"),
        "repository_url": repo.get("html_url") or repo.get("clone_url"),
        "description": repo.get("description"),
        "updated_at": repo.get("updated_at"),
        "repository_role": role["repository_role"],
        "artifact_channel_candidate": role["artifact_channel_candidate"],
        "already_configured": known is not None,
        "known_channel_id": known.get("id") if isinstance(known, dict) else None,
        "candidate_update_channel": update_channel,
    }


def _model_repository_role(repo: dict[str, object]) -> dict[str, object]:
    name = str(repo.get("name") or "").lower()
    description = str(repo.get("description") or "").lower()
    if name == "template-data-model" or "project template" in description:
        return {
            "repository_role": "model_development_template",
            "candidate_update_role": "model_template_version",
            "artifact_channel_candidate": False,
        }
    if name == "dp-architecture" or ("architecture" in name and "documentation" in description):
        return {
            "repository_role": "model_architecture_documentation",
            "candidate_update_role": "model_documentation_version",
            "artifact_channel_candidate": False,
        }
    return {
        "repository_role": "model_artifact",
        "candidate_update_role": "model_artifact_version",
        "artifact_channel_candidate": True,
    }


def _model_channel_id(repository_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", repository_name.lower()).strip("_")
    return f"{normalized}_tags"


def _filter_update_channels(
    channels: list[dict[str, object]],
    *,
    component_id: str | None,
    source_id: str | None,
    update_role: str | None,
) -> list[dict[str, object]]:
    result = channels
    if component_id:
        result = [channel for channel in result if channel.get("component_id") == component_id]
    if source_id:
        result = [channel for channel in result if channel.get("source_id") == source_id]
    if update_role:
        result = [channel for channel in result if channel.get("update_role") == update_role]
    return result


def _select_update_channels(
    channels: list[dict[str, object]],
    *,
    channel_ids: list[str],
    component_ids: list[str],
) -> list[dict[str, object]]:
    by_id = _by_id(channels)
    if channel_ids:
        unknown = [channel_id for channel_id in channel_ids if channel_id not in by_id]
        if unknown:
            raise InputError(f"Unknown update channel ids: {', '.join(unknown)}")
        return [by_id[channel_id] for channel_id in channel_ids]
    if component_ids:
        component_set = set(component_ids)
        return [channel for channel in channels if channel.get("component_id") in component_set]
    return channels


def _check_update_channel(channel: dict[str, object], timeout_seconds: float) -> dict[str, object]:
    kind = str(channel["kind"])
    method = "HEAD" if kind == "http_head" else "GET"
    response = _http_request_raw(str(channel["url"]), method, timeout_seconds)
    parsed = _parse_update_channel_payload(kind, response)
    return {
        "channel": _public_update_channel(channel),
        "response": _public_update_response(response),
        "current": parsed,
        "interpretation": _update_interpretation(channel, response, parsed),
    }


def _public_update_response(response: dict[str, object]) -> dict[str, object]:
    return {
        "url": response["url"],
        "available": response["available"],
        "status": response["status"],
        "reason": response["reason"],
        "headers": response["headers"],
        "body_bytes": response["body_bytes"],
        "body_truncated": response["body_truncated"],
    }


def _parse_update_channel_payload(kind: str, response: dict[str, object]) -> dict[str, object]:
    if not response.get("available"):
        return {"kind": kind, "latest_version": None, "latest_url": None, "published_at": None}
    if kind == "http_head":
        headers = response.get("headers", {})
        return {
            "kind": kind,
            "latest_version": None,
            "latest_url": response.get("url"),
            "published_at": headers.get("last_modified") if isinstance(headers, dict) else None,
            "etag": headers.get("etag") if isinstance(headers, dict) else None,
        }
    text = str(response.get("body_text") or "")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"kind": kind, "latest_version": None, "latest_url": response.get("url"), "published_at": None}
    if kind == "gitea_releases":
        release = _latest_release(payload)
        return {
            "kind": kind,
            "latest_version": release.get("tag_name") or release.get("name"),
            "latest_name": release.get("name"),
            "latest_url": release.get("html_url") or release.get("url"),
            "published_at": release.get("published_at") or release.get("created_at"),
            "prerelease": release.get("prerelease"),
            "draft": release.get("draft"),
        }
    if kind == "gitea_tags":
        tag = _latest_tag(payload)
        commit = tag.get("commit") if isinstance(tag.get("commit"), dict) else {}
        return {
            "kind": kind,
            "latest_version": tag.get("name"),
            "latest_url": tag.get("tarball_url") or tag.get("zipball_url"),
            "published_at": None,
            "commit_sha": commit.get("sha"),
        }
    if kind == "gitea_org_repos":
        repositories = _gitea_repositories(payload)
        return {
            "kind": kind,
            "repository_count": len(repositories),
            "repositories": repositories,
            "latest_version": None,
            "latest_url": response.get("url"),
            "published_at": None,
        }
    return {"kind": kind, "latest_version": None, "latest_url": response.get("url"), "published_at": None}


def _latest_release(payload: object) -> dict[str, object]:
    if isinstance(payload, list):
        releases = [item for item in payload if isinstance(item, dict) and not item.get("draft")]
        if not releases:
            return {}
        return sorted(
            releases,
            key=lambda item: str(item.get("published_at") or item.get("created_at") or item.get("tag_name") or ""),
            reverse=True,
        )[0]
    if isinstance(payload, dict):
        return payload
    return {}


def _latest_tag(payload: object) -> dict[str, object]:
    if not isinstance(payload, list):
        return {}
    tags = [item for item in payload if isinstance(item, dict) and isinstance(item.get("name"), str)]
    if not tags:
        return {}
    artifact_tags = [item for item in tags if str(item["name"]).startswith("pages-v")]
    if artifact_tags:
        tags = artifact_tags
    return sorted(tags, key=lambda item: _version_sort_key(str(item["name"])), reverse=True)[0]


def _gitea_repositories(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        return []
    repositories = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        repositories.append(
            {
                "name": item.get("name"),
                "full_name": item.get("full_name"),
                "html_url": item.get("html_url"),
                "clone_url": item.get("clone_url"),
                "description": item.get("description"),
                "updated_at": item.get("updated_at"),
                "archived": item.get("archived"),
            }
        )
    return sorted(repositories, key=lambda item: str(item["name"]))


def _version_sort_key(version: str) -> tuple[object, ...]:
    numbers = [int(item) for item in re.findall(r"\d+", version)]
    padded = (numbers[:4] + [0, 0, 0, 0])[:4]
    return (1 if numbers else 0, *padded, version)


def _update_interpretation(
    channel: dict[str, object],
    response: dict[str, object],
    parsed: dict[str, object],
) -> dict[str, object]:
    if not response.get("available"):
        return {
            "status": "unavailable",
            "message": "Remote channel could not be checked; use the stable local catalog and connected-source references.",
        }
    latest_version = parsed.get("latest_version")
    if latest_version:
        return {
            "status": "current_metadata_available",
            "message": f"Current metadata is available for {channel.get('title')}: {latest_version}.",
        }
    return {
        "status": "availability_metadata_available",
        "message": f"The channel is reachable, but no explicit version was parsed for {channel.get('title')}.",
    }


def _update_timeout_arg(arguments: dict[str, object], name: str) -> float:
    value = arguments.get(name)
    if value is None:
        return 5.0
    if not isinstance(value, (int, float)) or value <= 0 or value > 30:
        raise InputError(f"Tool argument '{name}' must be a number between 0 and 30.")
    return float(value)


def _component_ids_for_goal(user_goal: str | None, catalog: dict[str, Any]) -> list[str]:
    if not user_goal:
        return [str(component["id"]) for component in catalog["components"] if "id" in component]
    tokens = _tokens(user_goal)
    capabilities = _rank_records(catalog["capabilities"], tokens)
    component_ids = _component_ids_from_records(capabilities)
    return component_ids or [str(component["id"]) for component in catalog["components"] if "id" in component]


def _components_by_ids(component_ids: list[str], catalog: dict[str, Any]) -> list[dict[str, object]]:
    components = _by_id(catalog["components"])
    return [
        _public_component(components[component_id])
        for component_id in component_ids
        if component_id in components
    ]


def _deployment_target_arg(
    arguments: dict[str, object],
    name: str,
    *,
    required: bool,
) -> str | None:
    target = _string_arg(arguments, name, required=required)
    if target is None:
        return None
    normalized = target.strip().lower()
    if normalized not in {"compose", "kubernetes", "both"}:
        raise InputError(f"Tool argument '{name}' must be one of: compose, kubernetes, both.")
    return normalized


def _deployment_environment_arg(arguments: dict[str, object], name: str) -> str:
    value = _string_arg(arguments, name, required=False)
    if value is None:
        return "local"
    normalized = value.strip().lower()
    if normalized not in {"local", "dev", "prod"}:
        raise InputError(f"Tool argument '{name}' must be one of: local, dev, prod.")
    return normalized


def _deployment_templates_for_target(
    manifest: dict[str, Any],
    target: str | None,
) -> list[dict[str, object]]:
    templates = manifest["artifact_templates"]
    if target is None or target == "both":
        return templates
    return [template for template in templates if template.get("target") == target]


def _deployment_templates_by_ids(
    manifest: dict[str, Any],
    profile_ids: list[str],
) -> list[dict[str, object]]:
    by_id = _by_id(manifest["artifact_templates"])
    return [by_id[profile_id] for profile_id in profile_ids if profile_id in by_id]


def _deployment_profile_ids(
    target: str,
    include_re_indicators: bool,
    include_internal_adapter: bool,
) -> list[str]:
    profile_ids: list[str] = []
    if target in {"compose", "both"}:
        profile_ids.append("compose_baseline_external_adapter")
        if include_internal_adapter:
            profile_ids.append("compose_internal_adapter_profile")
        if include_re_indicators:
            profile_ids.append("compose_re_indicators_profile")
    if target in {"kubernetes", "both"}:
        profile_ids.extend(
            [
                "kubernetes_base",
                "kubernetes_dev_overlay",
                "kubernetes_prod_overlay",
            ]
        )
        if include_re_indicators:
            profile_ids.append("kubernetes_re_indicators_extension")
    return profile_ids


def _unique_strings(values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value not in result:
            result.append(value)
    return result


def _artifact_file(
    path: str,
    content: str,
    description: str,
    *,
    mime_type: str = "text/plain",
) -> dict[str, object]:
    return {
        "path": path,
        "mime_type": mime_type,
        "description": description,
        "content": content if content.endswith("\n") else content + "\n",
    }


def _generate_compose_artifacts(
    *,
    external_io_adapter_url: str,
    auth_mode: str,
    include_re_indicators: bool,
    include_internal_adapter: bool,
    version_context: dict[str, object],
) -> list[dict[str, object]]:
    compose = """services:
  hex-core-service:
    image: ${HEX_CORE_IMAGE}
    restart: unless-stopped
    env_file:
      - .env
    dns:
      - 1.1.1.1
      - 8.8.8.8
    environment:
      REGISTRY_CATALOG_FILE: /config/registry/catalog.json
    ports:
      - "${HEX_CORE_PORT}:8080"
    volumes:
      - ./registry/catalog.json:/config/registry/catalog.json:ro,Z
"""
    if include_re_indicators:
        compose += """
  re-indicators-calculation-service:
    profiles:
      - re-indicators
    image: ${RE_INDICATORS_CALC_IMAGE}
    restart: unless-stopped
    depends_on:
      hex-core-service:
        condition: service_started
    env_file:
      - .env
    dns:
      - 1.1.1.1
      - 8.8.8.8
    environment:
      HEX_CORE_BASE_URL: ${RE_INDICATORS_HEX_CORE_BASE_URL}
      ARTIFACT_BASE_URL_TEMPLATE: ${RE_INDICATORS_ARTIFACT_BASE_URL_TEMPLATE}
      HTTP_TIMEOUT_SECS: ${RE_INDICATORS_HTTP_TIMEOUT_SECS}
    ports:
      - "${RE_INDICATORS_CALC_PORT}:8081"
"""
    if include_internal_adapter:
        compose += """
  io-adapter:
    profiles:
      - internal-adapter
    image: ${IO_ADAPTER_IMAGE:-rg.fr-par.scw.cloud/ce-rise-software/dp-storage-jsondb:latest}
    restart: unless-stopped
"""
    return [
        _artifact_file(
            "compose/docker-compose.yml",
            compose,
            "Docker Compose starter derived from the CE-RISE GitOps template.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "compose/.env.example",
            _compose_env_example(external_io_adapter_url, auth_mode),
            "Example Compose environment file; replace URLs, auth, image tags, and ports before deployment.",
        ),
        _artifact_file(
            "compose/registry/catalog.json",
            _registry_catalog_json(version_context),
            "Pinned local registry catalog mounted into HEX Core Service.",
            mime_type="application/json",
        ),
        _artifact_file(
            "compose/README.md",
            _compose_readme(include_re_indicators, include_internal_adapter),
            "Compose usage notes for the generated starter artifact.",
            mime_type="text/markdown",
        ),
    ]


def _compose_env_example(external_io_adapter_url: str, auth_mode: str) -> str:
    return f"""# Image references
HEX_CORE_IMAGE=rg.fr-par.scw.cloud/ce-rise-software/hex-core-service:latest
RE_INDICATORS_CALC_IMAGE=rg.fr-par.scw.cloud/ce-rise-software/re-indicators-calculation:latest
IO_ADAPTER_IMAGE=rg.fr-par.scw.cloud/ce-rise-software/dp-storage-jsondb:latest

# Public exposure
HEX_CORE_PORT=8080
RE_INDICATORS_CALC_PORT=8083

# Core runtime
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
SERVER_REQUEST_MAX_BYTES=1048576
LOG_LEVEL=info
METRICS_ENABLED=false

# IO adapter
IO_ADAPTER_ID=http
IO_ADAPTER_BASE_URL={external_io_adapter_url}
IO_ADAPTER_TIMEOUT_MS=5000

# Optional RE indicators calculation service
RE_INDICATORS_HEX_CORE_BASE_URL=http://hex-core-service:8080
RE_INDICATORS_ARTIFACT_BASE_URL_TEMPLATE=https://ce-rise-models.codeberg.page/re-indicators-specification/generated/
RE_INDICATORS_HTTP_TIMEOUT_SECS=15

# Registry
REGISTRY_MODE=catalog
REGISTRY_CATALOG_FILE=/config/registry/catalog.json
REGISTRY_ALLOWED_HOSTS=codeberg.org
REGISTRY_REQUIRE_HTTPS=true
REGISTRY_CACHE_ENABLED=false
REGISTRY_CACHE_TTL_SECS=300

# Authentication
AUTH_MODE={auth_mode}
AUTH_JWKS_URL=https://keycloak.example.org/realms/ce-rise/protocol/openid-connect/certs
AUTH_ISSUER=https://keycloak.example.org/realms/ce-rise
AUTH_AUDIENCE=hex-core-service
AUTH_JWKS_REFRESH_SECS=3600
"""


def _compose_readme(include_re_indicators: bool, include_internal_adapter: bool) -> str:
    optional_profiles = []
    if include_internal_adapter:
        optional_profiles.append("internal-adapter")
    if include_re_indicators:
        optional_profiles.append("re-indicators")
    profile_note = ", ".join(optional_profiles) if optional_profiles else "none selected"
    return f"""# Compose Starter

This starter follows the CE-RISE Digital Passport System GitOps Template shape.

Default path:

- run `hex-core-service`;
- mount `compose/registry/catalog.json` as the local model registry catalog;
- point HEX Core Service at an external HTTP IO adapter.

Selected optional profiles: {profile_note}

Before deployment:

- copy `.env.example` to `.env` in your deployment workspace;
- replace URLs, image tags, auth settings, ports, and registry catalog entries;
- validate against the canonical CE-RISE GitOps template and component documentation.
"""


def _generate_kubernetes_artifacts(
    *,
    project_name: str,
    external_io_adapter_url: str,
    include_re_indicators: bool,
    version_context: dict[str, object],
) -> list[dict[str, object]]:
    slug = _slugify_project_name(project_name)
    files = [
        _artifact_file(
            "k8s/README.md",
            _kubernetes_readme(include_re_indicators),
            "Kubernetes usage notes for the generated starter artifact.",
            mime_type="text/markdown",
        ),
        _artifact_file(
            "k8s/base/kustomization.yaml",
            _k8s_base_kustomization(external_io_adapter_url),
            "Kubernetes base configuration for HEX Core Service.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/base/hex-core-deployment.yaml",
            _k8s_hex_core_deployment(),
            "HEX Core Service Kubernetes Deployment.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/base/hex-core-service.yaml",
            _k8s_hex_core_service(),
            "HEX Core Service Kubernetes Service.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/base/registry-configmap.yaml",
            _k8s_registry_configmap(version_context),
            "Registry catalog ConfigMap mounted by HEX Core Service.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/base/auth-secret.example.yaml",
            _k8s_auth_secret_example(),
            "Example auth Secret for JWT/JWKS settings. Replace before production use.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/dev/kustomization.yaml",
            _k8s_dev_kustomization(slug),
            "Development overlay with debug logging and non-production auth settings.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/dev/namespace.yaml",
            _k8s_namespace(f"{slug}-dev"),
            "Development namespace.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/dev/patch-hex-core-deployment.yaml",
            _k8s_dev_patch(),
            "Development Deployment patch.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/prod/kustomization.yaml",
            _k8s_prod_kustomization(slug, external_io_adapter_url),
            "Production overlay with JWT/JWKS placeholders.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/prod/namespace.yaml",
            _k8s_namespace(f"{slug}-prod"),
            "Production namespace.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/prod/patch-hex-core-deployment.yaml",
            _k8s_prod_patch(),
            "Production Deployment patch with replica and resource placeholders.",
            mime_type="application/yaml",
        ),
        _artifact_file(
            "k8s/overlays/prod/auth-secret.example.yaml",
            _k8s_auth_secret_example(),
            "Production auth Secret example. Replace with the operator's secret workflow.",
            mime_type="application/yaml",
        ),
    ]
    if include_re_indicators:
        files.extend(
            [
                _artifact_file(
                    "k8s/extensions/re-indicators/kustomization.yaml",
                    _k8s_re_indicators_kustomization(),
                    "Kubernetes extension for RE Indicators Calculation Service.",
                    mime_type="application/yaml",
                ),
                _artifact_file(
                    "k8s/extensions/re-indicators/deployment.yaml",
                    _k8s_re_indicators_deployment(),
                    "RE Indicators Calculation Service Deployment.",
                    mime_type="application/yaml",
                ),
                _artifact_file(
                    "k8s/extensions/re-indicators/service.yaml",
                    _k8s_re_indicators_service(),
                    "RE Indicators Calculation Service Service.",
                    mime_type="application/yaml",
                ),
                _artifact_file(
                    "k8s/overlays/dev-re-indicators/kustomization.yaml",
                    _k8s_re_indicators_overlay(f"{slug}-dev", "../dev"),
                    "Development overlay that includes the RE indicators extension.",
                    mime_type="application/yaml",
                ),
                _artifact_file(
                    "k8s/overlays/prod-re-indicators/kustomization.yaml",
                    _k8s_re_indicators_overlay(f"{slug}-prod", "../prod"),
                    "Production overlay that includes the RE indicators extension.",
                    mime_type="application/yaml",
                ),
            ]
        )
    return files


def _registry_catalog_json(version_context: dict[str, object] | None = None) -> str:
    catalog = {"models": _registry_catalog_models(version_context or {})}
    return json.dumps(catalog, indent=2)


def _kubernetes_readme(include_re_indicators: bool) -> str:
    extension_line = (
        "- use `k8s/overlays/dev-re-indicators` or `k8s/overlays/prod-re-indicators` when the RE indicators extension is needed;"
        if include_re_indicators
        else "- add optional extensions only when the selected Digital Passport workflow needs them;"
    )
    return f"""# Kubernetes Starter

This starter follows the CE-RISE Digital Passport System GitOps Template shape.

Baseline:

- `k8s/base` defines HEX Core Service, service exposure, configuration, and registry catalog mounting;
- `k8s/overlays/dev` is for development and uses insecure auth only for non-production testing;
- `k8s/overlays/prod` is for production planning and includes JWT/JWKS placeholders;
{extension_line}
- replace secrets, domains, image tags, resource limits, and registry entries before deployment.

Validate these files against the canonical CE-RISE GitOps template before operational use.
"""


def _k8s_base_kustomization(external_io_adapter_url: str) -> str:
    return f"""apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - hex-core-deployment.yaml
  - hex-core-service.yaml
  - registry-configmap.yaml

configMapGenerator:
  - name: hex-core-env
    literals:
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8080
      - SERVER_REQUEST_MAX_BYTES=1048576
      - LOG_LEVEL=info
      - METRICS_ENABLED=false
      - IO_ADAPTER_ID=http
      - IO_ADAPTER_BASE_URL={external_io_adapter_url}
      - IO_ADAPTER_TIMEOUT_MS=5000
      - REGISTRY_MODE=catalog
      - REGISTRY_CATALOG_FILE=/config/registry/catalog.json
      - REGISTRY_ALLOWED_HOSTS=codeberg.org
      - REGISTRY_REQUIRE_HTTPS=true
      - AUTH_MODE=jwt_jwks
      - AUTH_AUDIENCE=hex-core-service

generatorOptions:
  disableNameSuffixHash: true
"""


def _k8s_hex_core_deployment() -> str:
    return """apiVersion: apps/v1
kind: Deployment
metadata:
  name: hex-core-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hex-core-service
  template:
    metadata:
      labels:
        app: hex-core-service
    spec:
      containers:
        - name: hex-core-service
          image: rg.fr-par.scw.cloud/ce-rise-software/hex-core-service:latest
          ports:
            - containerPort: 8080
          envFrom:
            - configMapRef:
                name: hex-core-env
            - secretRef:
                name: hex-core-auth
          volumeMounts:
            - name: registry-catalog
              mountPath: /config/registry
              readOnly: true
      volumes:
        - name: registry-catalog
          configMap:
            name: registry-catalog
"""


def _k8s_hex_core_service() -> str:
    return """apiVersion: v1
kind: Service
metadata:
  name: hex-core-service
spec:
  selector:
    app: hex-core-service
  ports:
    - name: http
      port: 8080
      targetPort: 8080
"""


def _k8s_registry_configmap(version_context: dict[str, object]) -> str:
    return f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: registry-catalog
data:
  catalog.json: |
{_indent_text(_registry_catalog_json(version_context), 4)}
"""


def _k8s_auth_secret_example() -> str:
    return """apiVersion: v1
kind: Secret
metadata:
  name: hex-core-auth
type: Opaque
stringData:
  AUTH_JWKS_URL: https://keycloak.example.org/realms/ce-rise/protocol/openid-connect/certs
  AUTH_ISSUER: https://keycloak.example.org/realms/ce-rise
"""


def _k8s_dev_kustomization(slug: str) -> str:
    return f"""apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: {slug}-dev

resources:
  - ../../base
  - namespace.yaml

patches:
  - path: patch-hex-core-deployment.yaml

configMapGenerator:
  - name: hex-core-env
    behavior: merge
    literals:
      - LOG_LEVEL=debug
      - IO_ADAPTER_BASE_URL=http://io-adapter.dev.svc.cluster.local
      - AUTH_MODE=none
      - AUTH_ALLOW_INSECURE_NONE=true

secretGenerator:
  - name: hex-core-auth
    behavior: create
    literals: []

generatorOptions:
  disableNameSuffixHash: true
"""


def _k8s_prod_kustomization(slug: str, external_io_adapter_url: str) -> str:
    return f"""apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: {slug}-prod

resources:
  - ../../base
  - namespace.yaml
  - auth-secret.example.yaml

patches:
  - path: patch-hex-core-deployment.yaml

configMapGenerator:
  - name: hex-core-env
    behavior: merge
    literals:
      - LOG_LEVEL=info
      - IO_ADAPTER_BASE_URL={external_io_adapter_url}
      - AUTH_MODE=jwt_jwks
      - AUTH_AUDIENCE=hex-core-service

generatorOptions:
  disableNameSuffixHash: true
"""


def _k8s_namespace(name: str) -> str:
    return f"""apiVersion: v1
kind: Namespace
metadata:
  name: {name}
"""


def _k8s_dev_patch() -> str:
    return """apiVersion: apps/v1
kind: Deployment
metadata:
  name: hex-core-service
spec:
  template:
    spec:
      containers:
        - name: hex-core-service
          imagePullPolicy: IfNotPresent
"""


def _k8s_prod_patch() -> str:
    return """apiVersion: apps/v1
kind: Deployment
metadata:
  name: hex-core-service
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: hex-core-service
          imagePullPolicy: IfNotPresent
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "1Gi"
"""


def _k8s_re_indicators_kustomization() -> str:
    return """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml
  - service.yaml

configMapGenerator:
  - name: re-indicators-env
    literals:
      - HEX_CORE_BASE_URL=http://hex-core-service:8080
      - ARTIFACT_BASE_URL_TEMPLATE=https://ce-rise-models.codeberg.page/re-indicators-specification/generated/
      - HTTP_TIMEOUT_SECS=15

generatorOptions:
  disableNameSuffixHash: true
"""


def _k8s_re_indicators_deployment() -> str:
    return """apiVersion: apps/v1
kind: Deployment
metadata:
  name: re-indicators-calculation-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: re-indicators-calculation-service
  template:
    metadata:
      labels:
        app: re-indicators-calculation-service
    spec:
      containers:
        - name: re-indicators-calculation-service
          image: rg.fr-par.scw.cloud/ce-rise-software/re-indicators-calculation:latest
          ports:
            - containerPort: 8081
          envFrom:
            - configMapRef:
                name: re-indicators-env
"""


def _k8s_re_indicators_service() -> str:
    return """apiVersion: v1
kind: Service
metadata:
  name: re-indicators-calculation-service
spec:
  selector:
    app: re-indicators-calculation-service
  ports:
    - port: 8081
      targetPort: 8081
"""


def _k8s_re_indicators_overlay(namespace: str, base_overlay: str) -> str:
    return f"""apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: {namespace}

resources:
  - {base_overlay}
  - ../../extensions/re-indicators
"""


def _indent_text(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else prefix for line in text.splitlines())


def _slugify_project_name(project_name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", project_name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return (slug[:50].strip("-") or "ce-rise-dp-system")


def _deployment_validation_commands(
    target: str,
    *,
    include_re_indicators: bool,
    include_internal_adapter: bool,
) -> list[str]:
    commands = []
    if target in {"compose", "both"}:
        profile_args = []
        if include_internal_adapter:
            profile_args.append("--profile internal-adapter")
        if include_re_indicators:
            profile_args.append("--profile re-indicators")
        profile_segment = f" {' '.join(profile_args)}" if profile_args else ""
        commands.append(
            f"docker compose -f compose/docker-compose.yml --env-file compose/.env.example{profile_segment} config"
        )
    if target in {"kubernetes", "both"}:
        commands.extend(
            [
                "kubectl kustomize k8s/overlays/dev",
                "kubectl kustomize k8s/overlays/prod",
            ]
        )
        if include_re_indicators:
            commands.extend(
                [
                    "kubectl kustomize k8s/overlays/dev-re-indicators",
                    "kubectl kustomize k8s/overlays/prod-re-indicators",
                ]
            )
    return commands


def _deployment_readiness_next_action(readiness_level: str) -> str:
    if readiness_level == "ready_for_template_validation":
        return "Generate the deployment artifacts and validate them against the canonical CE-RISE GitOps template workflow."
    if readiness_level == "partial":
        return "Fill the missing deployment decisions before treating generated artifacts as implementation-ready."
    return "Start by selecting runtime, services, IO adapter strategy, registry strategy, and authentication approach."


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _components_from_records(records: list[dict[str, object]], catalog: dict[str, Any]) -> list[dict[str, object]]:
    component_ids: list[str] = []
    for record in records:
        for component_id in record.get("related_components", []):
            if isinstance(component_id, str) and component_id not in component_ids:
                component_ids.append(component_id)
        for component_id in record.get("component_sequence", []):
            if isinstance(component_id, str) and component_id not in component_ids:
                component_ids.append(component_id)
    components = _by_id(catalog["components"])
    return [
        _public_component(components[component_id])
        for component_id in component_ids
        if component_id in components
    ]


def _component_ids_from_records(records: list[dict[str, object]]) -> list[str]:
    component_ids: list[str] = []
    for record in records:
        for field in ("related_components", "component_sequence"):
            for component_id in record.get(field, []):
                if isinstance(component_id, str) and component_id not in component_ids:
                    component_ids.append(component_id)
    return component_ids


def _component_ids_from_components(components: list[dict[str, object]]) -> list[str]:
    component_ids: list[str] = []
    for component in components:
        component_id = component.get("id")
        if isinstance(component_id, str) and component_id not in component_ids:
            component_ids.append(component_id)
    return component_ids


def _source_references_for_components(component_ids: list[str]) -> list[dict[str, object]]:
    manifest = _load_sources()
    component_set = set(component_ids)
    return [
        _public_source(source)
        for source in manifest["sources"]
        if source.get("component_id") in component_set
    ]


def _live_service_connections_for_components(component_ids: list[str]) -> list[dict[str, object]]:
    manifest = _load_live_services()
    component_set = set(component_ids)
    return [
        _public_live_service(service)
        for service in manifest["services"]
        if service.get("component_id") in component_set
    ]


def _update_awareness_for_components(component_ids: list[str]) -> dict[str, object]:
    unique_component_ids = _unique_strings(component_ids)
    manifest = _load_update_channels()
    channels = _select_update_channels(
        manifest["channels"],
        channel_ids=[],
        component_ids=unique_component_ids,
    )
    status = "current_metadata_not_checked" if channels else "no_update_channels_configured"
    if channels:
        message = (
            "This result may depend on current CE-RISE component, model, example, documentation, "
            "or deployment-template versions. Remote metadata was not checked in this tool call."
        )
    else:
        message = "No configured update channels are available for the selected components."
    return {
        "status": status,
        "message": message,
        "selected_component_ids": unique_component_ids,
        "update_channel_count": len(channels),
        "update_channels": [_public_update_channel(channel) for channel in channels],
        "recommended_next_tools": [
            "build_update_aware_solution_context",
            "check_update_channels",
        ] if channels else [],
        "recommended_action": (
            "Before implementation, deployment, or detailed technical advice, run "
            "build_update_aware_solution_context with check_remote=true or check_update_channels "
            "for the relevant channels."
        ) if channels else "Use connected-source inspection and stable catalog guidance.",
    }


def _version_context_for_components(
    component_ids: list[str],
    *,
    check_remote: bool,
    timeout_seconds: float,
) -> dict[str, object]:
    unique_component_ids = _unique_strings(component_ids)
    manifest = _load_update_channels()
    channels = _select_update_channels(
        manifest["channels"],
        channel_ids=[],
        component_ids=unique_component_ids,
    )
    checks = [_check_update_channel(channel, timeout_seconds) for channel in channels] if check_remote else []
    resolved_versions = _resolved_versions_from_checks(checks)
    update_awareness = _update_awareness_for_components(unique_component_ids)
    if check_remote:
        update_awareness = {
            **update_awareness,
            "status": "current_metadata_checked",
            "message": "Configured update channels were checked and their current metadata is included in version_context.",
            "recommended_action": "Review current metadata before applying generated artifacts.",
        }
    return {
        "policy": "current_metadata_when_checked" if check_remote else "stable_manifest_with_update_notice",
        "remote_checked": check_remote,
        "timeout_seconds": timeout_seconds,
        "component_ids": unique_component_ids,
        "update_channels": [_public_update_channel(channel) for channel in channels],
        "update_checks": checks,
        "resolved_versions": resolved_versions,
        "update_awareness": update_awareness,
        "application_note": (
            "Generated artifact contents use current checked metadata where the channel maps cleanly "
            "to an artifact field; otherwise they include the metadata for review."
        ) if check_remote else (
            "Generated artifact contents use stable manifest defaults. Run the same generation call "
            "with check_remote_updates=true to include current upstream metadata."
        ),
    }


def _resolved_versions_from_checks(checks: list[dict[str, object]]) -> list[dict[str, object]]:
    resolved = []
    for check in checks:
        channel = check.get("channel")
        current = check.get("current")
        if not isinstance(channel, dict) or not isinstance(current, dict):
            continue
        latest_version = current.get("latest_version")
        if not latest_version:
            continue
        resolved.append(
            {
                "channel_id": channel.get("id"),
                "component_id": channel.get("component_id"),
                "source_id": channel.get("source_id"),
                "update_role": channel.get("update_role"),
                "version": latest_version,
                "url": current.get("latest_url"),
                "channel_url": channel.get("url"),
                "published_at": current.get("published_at"),
            }
        )
    return resolved


def _resolved_version_by_channel(version_context: dict[str, object]) -> dict[str, dict[str, object]]:
    resolved = version_context.get("resolved_versions")
    if not isinstance(resolved, list):
        return {}
    return {
        str(item["channel_id"]): item
        for item in resolved
        if isinstance(item, dict) and isinstance(item.get("channel_id"), str)
    }


def _registry_catalog_models(version_context: dict[str, object]) -> list[dict[str, object]]:
    baseline_model_channels = {
        "dp-record-metadata": ("dp_record_metadata_tags", "0.0.2"),
        "product-profile": ("product_profile_tags", "0.0.3"),
        "usage-and-maintenance": ("usage_and_maintenance_tags", "0.0.2"),
        "re-indicators-specification": ("re_indicators_specification_tags", "0.0.5"),
    }
    by_channel = _resolved_version_by_channel(version_context)
    model_specs = [
        {
            "model": model_name,
            "channel_id": channel_id,
            "default_version": default_version,
        }
        for model_name, (channel_id, default_version) in baseline_model_channels.items()
    ]
    if version_context.get("remote_checked"):
        baseline_channel_ids = {
            str(item["channel_id"])
            for item in model_specs
            if isinstance(item.get("channel_id"), str)
        }
        dynamic_specs = []
        for item in by_channel.values():
            if item.get("update_role") != "model_artifact_version":
                continue
            channel_id = item.get("channel_id")
            latest_version = item.get("version")
            if channel_id in baseline_channel_ids or not isinstance(latest_version, str):
                continue
            if not latest_version.startswith("pages-v"):
                continue
            model_name = _model_name_from_channel_url(str(item.get("channel_url") or item.get("url") or ""))
            if not model_name:
                continue
            dynamic_specs.append(
                {
                    "model": model_name,
                    "channel_id": channel_id,
                    "default_version": None,
                }
            )
        model_specs.extend(sorted(dynamic_specs, key=lambda item: str(item["model"])))
    models = []
    for spec in model_specs:
        model_name = str(spec["model"])
        channel_id = str(spec["channel_id"])
        default_version = spec.get("default_version")
        version = _model_version_from_tag(str(by_channel.get(channel_id, {}).get("version") or default_version))
        if not version or version == "None":
            continue
        models.append(
            {
                "model": model_name,
                "version": version,
                "schema_url": _ce_rise_model_artifact_url(model_name, version, "schema.json"),
                "shacl_url": _ce_rise_model_artifact_url(model_name, version, "shacl.ttl"),
            }
        )
    return models


def _model_name_from_channel_url(url: str) -> str | None:
    match = re.search(r"/repos/CE-RISE-models/([^/]+)/tags(?:\?|$)", url)
    if not match:
        return None
    return match.group(1)


def _ce_rise_model_artifact_url(model_name: str, version: str, artifact_name: str) -> str:
    return f"https://codeberg.org/CE-RISE-models/{model_name}/raw/tag/pages-v{version}/generated/{artifact_name}"


def _model_version_from_tag(tag: str) -> str:
    if tag.startswith("pages-v"):
        return tag.removeprefix("pages-v")
    if tag.startswith("v") and re.match(r"^v\d", tag):
        return tag[1:]
    return tag


def _version_context_markdown(version_context: dict[str, object]) -> str:
    lines = [
        "# Version Context",
        "",
        f"Policy: `{version_context.get('policy')}`",
        f"Remote checked: `{str(version_context.get('remote_checked')).lower()}`",
        "",
        str(version_context.get("application_note") or ""),
        "",
        "## Components",
        "",
    ]
    for component_id in version_context.get("component_ids", []):
        lines.append(f"- `{component_id}`")
    lines.extend(["", "## Update Channels", ""])
    for channel in version_context.get("update_channels", []):
        if isinstance(channel, dict):
            lines.append(f"- `{channel.get('id')}` ({channel.get('update_role')})")
    resolved = version_context.get("resolved_versions")
    if isinstance(resolved, list) and resolved:
        lines.extend(["", "## Resolved Versions", ""])
        for item in resolved:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('channel_id')}`: `{item.get('version')}`"
                )
    else:
        lines.extend(["", "## Resolved Versions", "", "- No current upstream versions were resolved in this generation call."])
    lines.extend(
        [
            "",
            "Review this context before implementation or deployment decisions.",
        ]
    )
    return "\n".join(lines)


def _component_sequence(record: dict[str, object], catalog: dict[str, Any]) -> list[dict[str, object]]:
    components = _by_id(catalog["components"])
    return [
        _public_component(components[component_id])
        for component_id in record.get("component_sequence", [])
        if component_id in components
    ]


def _phase_components(phase_id: str, path: dict[str, object]) -> list[str]:
    if "model" in phase_id or "coverage" in phase_id or "validate" in phase_id:
        return ["ce_rise_models"]
    if "local" in phase_id or "demonstrator" in phase_id:
        return ["dp_system_local_demonstrator", "hex_core_service", "dp_storage_jsondb_service"]
    if "gitops" in phase_id or "operational" in phase_id or "deployment" in phase_id:
        return ["dp_system_gitops_template", "hex_core_service", "dp_storage_jsondb_service"]
    return [item for item in path.get("component_sequence", []) if isinstance(item, str)]


def _phase_detail(phase_id: str) -> dict[str, object]:
    details = {
        "scope_adoption_context": {
            "title": "Scope the adoption context",
            "objective": "Clarify why the Digital Passport is needed and what it should cover.",
            "actions": ["Declare organization role, passport scope, compliance drivers, value goals, and constraints."],
            "completion_evidence": ["Adoption context fields are documented."]
        },
        "map_information_flows": {
            "title": "Map value-chain information flows",
            "objective": "Identify information that must be requested, held, validated, enriched, or shared.",
            "actions": ["List actors, information types, authoritative sources, recipients, and validation responsibilities."],
            "completion_evidence": ["Information flow map exists with sources and open questions."]
        },
        "assess_readiness": {
            "title": "Assess adoption and implementation readiness",
            "objective": "Find missing information before implementation planning.",
            "actions": ["Run readiness checks and document missing fields, risks, and assumptions."],
            "completion_evidence": ["Readiness result has a concrete next action."]
        },
        "select_reuse_path": {
            "title": "Select the CE-RISE reuse path",
            "objective": "Choose which existing CE-RISE assets should support the next implementation step.",
            "actions": ["Select a reference-example, model-first, value-chain exchange, or deployment preparation path."],
            "completion_evidence": ["Selected CE-RISE path and component sequence are documented."]
        },
        "select_local_components": {
            "title": "Select local prototype components",
            "objective": "Prepare a local CE-RISE component set for prototype learning and validation.",
            "actions": ["Review the local demonstrator as an example and select the service components needed for the declared scope."],
            "completion_evidence": ["Local component choices and assumptions are documented."]
        },
        "run_local_demonstrator": {
            "title": "Generalize the local demonstrator pattern",
            "objective": "Use the demonstrator as an example of component interaction while adapting scope, payloads, checks, and configuration to the adopter context.",
            "actions": ["Run or inspect the CE-RISE local demonstrator, identify reusable workflow patterns, and record what must change for the declared scope."],
            "completion_evidence": ["Reusable patterns, non-reusable demo assumptions, and context-specific gaps are recorded."]
        },
        "validate_model_and_data": {
            "title": "Validate model and data readiness",
            "objective": "Check whether declared information needs align with model and validation assets.",
            "actions": ["Use CE-RISE model assets and document coverage questions or gaps."],
            "completion_evidence": ["Model coverage or gap result is available."]
        },
        "scope_information_requirements": {
            "title": "Scope information requirements",
            "objective": "Turn compliance drivers and value goals into concrete information requirements.",
            "actions": ["List fields, joins, evidence needs, and actor responsibilities."],
            "completion_evidence": ["Information requirements are explicit enough for model assessment."]
        },
        "select_model_sources": {
            "title": "Select model sources",
            "objective": "Identify CE-RISE model assets and related schemas relevant to the passport scope.",
            "actions": ["Select candidate schemas, SHACL assets, and use-case coverage targets."],
            "completion_evidence": ["Candidate model sources are documented."]
        },
        "assess_model_coverage": {
            "title": "Assess model coverage",
            "objective": "Use model assessment to compare information needs against available model assets.",
            "actions": ["Review available CE-RISE model artifacts against the declared information needs."],
            "completion_evidence": ["Coverage result or assessment plan exists."]
        },
        "prioritize_model_gaps": {
            "title": "Prioritize model gaps",
            "objective": "Rank missing fields, joins, or model coverage issues before implementation.",
            "actions": ["Use assessment outputs to decide what must be configured, clarified, or deferred."],
            "completion_evidence": ["Prioritized gap list exists."]
        },
        "map_actors": {
            "title": "Map value-chain actors",
            "objective": "Identify actors that provide, consume, validate, or enrich Digital Passport information.",
            "actions": ["List upstream, internal, downstream, and return-loop actors."],
            "completion_evidence": ["Actor map exists."]
        },
        "classify_shared_information": {
            "title": "Classify shared information",
            "objective": "Classify information flows into identity, material, lifecycle, compliance, circularity, and end-of-life groups.",
            "actions": ["Use the catalog flow types as a first classification layer."],
            "completion_evidence": ["Information flows are classified."]
        },
        "validate_exchange_readiness": {
            "title": "Validate exchange readiness",
            "objective": "Check whether shared information has sources, recipients, formats, and validation responsibilities.",
            "actions": ["Document open exchange questions and map them to CE-RISE assets."],
            "completion_evidence": ["Exchange readiness gaps are documented."]
        },
        "confirm_component_choices": {
            "title": "Confirm component choices",
            "objective": "Confirm the CE-RISE services, storage, models, and deployment templates needed for the next stage.",
            "actions": ["Record selected components, versions, configuration assumptions, and ownership."],
            "completion_evidence": ["Component choices are confirmed."]
        },
        "document_configuration": {
            "title": "Document configuration",
            "objective": "Turn prototype decisions into deployable configuration requirements.",
            "actions": ["Document service settings, storage assumptions, model assets, and validation checks."],
            "completion_evidence": ["Configuration notes are ready for deployment planning."]
        },
        "map_to_gitops_template": {
            "title": "Map to GitOps template",
            "objective": "Use the existing CE-RISE GitOps template as the deployment preparation path.",
            "actions": ["Map selected services and configuration assumptions to the GitOps template."],
            "completion_evidence": ["GitOps mapping is documented."]
        },
        "plan_operational_checks": {
            "title": "Plan operational checks",
            "objective": "Define checks for deployment readiness, data updates, validation, and monitoring.",
            "actions": ["List smoke checks, data checks, and model validation checks for the target deployment."],
            "completion_evidence": ["Operational check list exists."]
        }
    }
    fallback = {
        "title": phase_id.replace("_", " ").title(),
        "objective": "Complete this roadmap phase using the selected CE-RISE reuse path.",
        "actions": ["Clarify the phase objective, required inputs, CE-RISE assets, and completion evidence."],
        "completion_evidence": ["Phase output is documented."]
    }
    detail = details.get(phase_id, fallback)
    return {"id": phase_id, **detail}


def list_connected_sources(arguments: dict[str, object]) -> dict[str, object]:
    source_kind = _string_arg(arguments, "kind", required=False)
    include_status = _bool_arg(arguments, "include_status", default=False)
    manifest = _load_sources()
    sources = manifest["sources"]
    if source_kind:
        sources = [item for item in sources if item.get("kind") == source_kind]
    public_sources = []
    for source in sources:
        item = _public_source(source)
        if include_status:
            item["local_status"] = _local_source_status(source)
        public_sources.append(item)
    return _result(
        "connected_sources_result",
        {"kind": source_kind, "include_status": include_status},
        {
            "manifest_version": manifest["manifest_version"],
            "scope_note": manifest["scope_note"],
            "sources": public_sources,
        },
    )


def check_connected_sources(arguments: dict[str, object]) -> dict[str, object]:
    source_ids = _string_list_arg(arguments, "source_ids")
    check_remote = _bool_arg(arguments, "check_remote", default=False)
    manifest = _load_sources()
    sources = _filter_sources(manifest["sources"], source_ids)
    checks = []
    for source in sources:
        check = {
            "source": _public_source(source),
            "local_status": _local_source_status(source),
            "remote_status": [],
        }
        if check_remote:
            for field in ("repository_url", "documentation_url"):
                status = _remote_url_status(source.get(field), timeout_seconds=3.0)
                if status is not None:
                    check["remote_status"].append({"field": field, **status})
        checks.append(check)
    diagnostics = []
    if not check_remote:
        diagnostics.append(
            {
                "level": "info",
                "message": "Remote URL checks were not performed. Pass check_remote=true to test network availability.",
            }
        )
    return _result(
        "connected_source_availability_result",
        {"source_ids": source_ids, "check_remote": check_remote},
        {"checks": checks},
        diagnostics=diagnostics,
    )


def inspect_connected_source(arguments: dict[str, object]) -> dict[str, object]:
    source_id = _string_arg(arguments, "source_id")
    include_headings = _bool_arg(arguments, "include_headings", default=True)
    manifest = _load_sources()
    source = _source_by_id(manifest["sources"], source_id)
    local_status = _local_source_status(source)
    files = []
    for key_file in source.get("key_files", []):
        if not isinstance(key_file, str):
            continue
        file_path = _safe_source_file(source, key_file)
        file_info = {
            "path": key_file,
            "exists": file_path.is_file(),
            "size_bytes": file_path.stat().st_size if file_path.is_file() else None,
            "headings": [],
        }
        if include_headings and file_path.is_file():
            file_info["headings"] = _markdown_headings(file_path)
        files.append(file_info)
    return _result(
        "connected_source_inspection_result",
        {"source_id": source_id, "include_headings": include_headings},
        {
            "source": _public_source(source),
            "local_status": local_status,
            "files": files,
            "connection_note": "Inspection reads only curated key files from the connected CE-RISE source manifest.",
        },
    )


def build_connected_solution_snapshot(arguments: dict[str, object]) -> dict[str, object]:
    source_ids = _string_list_arg(arguments, "source_ids")
    include_headings = _bool_arg(arguments, "include_headings", default=False)
    manifest = _load_sources()
    catalog = _load_catalog()
    sources = _filter_sources(manifest["sources"], source_ids)
    components = _by_id(catalog["components"])
    component_ids: list[str] = []
    snapshot_sources = []
    for source in sources:
        source_item = _public_source(source)
        source_item["local_status"] = _local_source_status(source)
        component_id = source.get("component_id")
        if isinstance(component_id, str) and component_id in components:
            component_ids.append(component_id)
            source_item["catalog_component"] = _public_component(components[component_id])
        if include_headings:
            source_item["key_file_headings"] = [
                {
                    "path": key_file,
                    "headings": _markdown_headings(_safe_source_file(source, key_file)),
                }
                for key_file in source.get("key_files", [])
                if isinstance(key_file, str) and _safe_source_file(source, key_file).is_file()
            ]
        snapshot_sources.append(source_item)
    return _result(
        "connected_solution_snapshot_result",
        {"source_ids": source_ids, "include_headings": include_headings},
        {
            "catalog_version": catalog["catalog_version"],
            "manifest_version": manifest["manifest_version"],
            "sources": snapshot_sources,
            "update_awareness": _update_awareness_for_components(component_ids),
            "next_use": [
                "Use inspect_connected_source for details on a specific CE-RISE source.",
                "Use existing adoption and implementation tools to map user goals to these connected sources.",
            ],
        },
    )


def list_live_service_connections(arguments: dict[str, object]) -> dict[str, object]:
    service_family = _string_arg(arguments, "service_family", required=False)
    manifest = _load_live_services()
    services = manifest["services"]
    if service_family:
        services = [item for item in services if item.get("service_family") == service_family]
    component_ids = [
        str(service["component_id"])
        for service in services
        if isinstance(service.get("component_id"), str)
    ]
    return _result(
        "live_service_connections_result",
        {"service_family": service_family},
        {
            "manifest_version": manifest["manifest_version"],
            "scope_note": manifest["scope_note"],
            "services": [_public_live_service(item) for item in services],
            "update_awareness": _update_awareness_for_components(component_ids),
        },
    )


def probe_live_service(arguments: dict[str, object]) -> dict[str, object]:
    service_id = _string_arg(arguments, "service_id")
    endpoint_ids = _string_list_arg(arguments, "endpoint_ids")
    base_url_override = _string_arg(arguments, "base_url", required=False)
    timeout_seconds = _timeout_arg(arguments, "timeout_seconds")
    manifest = _load_live_services()
    service = _live_service_by_id(manifest["services"], service_id)
    base_url = _safe_base_url(service, base_url_override)
    endpoints = [
        _endpoint_by_id(service, endpoint_id)
        for endpoint_id in endpoint_ids
    ] if endpoint_ids else list(service.get("safe_endpoints", []))
    probes = []
    for endpoint in endpoints:
        if endpoint.get("method") != "GET":
            raise InputError(f"Only GET endpoints can be probed: {endpoint.get('id')}")
        url = _join_url(base_url, endpoint.get("path"))
        probes.append(
            {
                "endpoint": endpoint,
                "response": _http_get(url, timeout_seconds),
            }
        )
    return _result(
        "live_service_probe_result",
        {
            "service_id": service_id,
            "endpoint_ids": endpoint_ids,
            "base_url": base_url_override,
            "timeout_seconds": timeout_seconds,
        },
        {
            "service": _public_live_service(service),
            "effective_base_url": base_url,
            "probes": probes,
            "update_awareness": _update_awareness_for_components([str(service.get("component_id"))]),
        },
        diagnostics=[
            {
                "level": "info",
                "message": "Only curated read-only GET endpoints were probed.",
            }
        ],
    )


def inspect_live_service_openapi(arguments: dict[str, object]) -> dict[str, object]:
    service_id = _string_arg(arguments, "service_id")
    base_url_override = _string_arg(arguments, "base_url", required=False)
    timeout_seconds = _timeout_arg(arguments, "timeout_seconds")
    manifest = _load_live_services()
    service = _live_service_by_id(manifest["services"], service_id)
    endpoint = _endpoint_by_id(service, "openapi")
    base_url = _safe_base_url(service, base_url_override)
    response = _http_get(_join_url(base_url, endpoint["path"]), timeout_seconds)
    return _result(
        "live_service_openapi_inspection_result",
        {
            "service_id": service_id,
            "base_url": base_url_override,
            "timeout_seconds": timeout_seconds,
        },
        {
            "service": _public_live_service(service),
            "effective_base_url": base_url,
            "endpoint": endpoint,
            "response": response,
            "openapi_summary": _openapi_summary_from_response(response),
            "update_awareness": _update_awareness_for_components([str(service.get("component_id"))]),
        },
    )


def build_live_service_readiness_snapshot(arguments: dict[str, object]) -> dict[str, object]:
    service_ids = _string_list_arg(arguments, "service_ids")
    timeout_seconds = _timeout_arg(arguments, "timeout_seconds")
    manifest = _load_live_services()
    services = _filter_live_services(manifest["services"], service_ids)
    snapshots = []
    for service in services:
        endpoint_ids = [
            str(endpoint["id"])
            for endpoint in service.get("safe_endpoints", [])
            if isinstance(endpoint, dict) and endpoint.get("id") in {"health", "ready", "version"}
        ]
        if not endpoint_ids:
            endpoint_ids = [
                str(endpoint["id"])
                for endpoint in service.get("safe_endpoints", [])
                if isinstance(endpoint, dict) and endpoint.get("id") == "health"
            ]
        probe = probe_live_service(
            {
                "service_id": service["id"],
                "endpoint_ids": endpoint_ids,
                "timeout_seconds": timeout_seconds,
            }
        )
        probes = probe["content"]["probes"]
        available_count = sum(1 for item in probes if item["response"].get("available"))
        snapshots.append(
            {
                "service": _public_live_service(service),
                "effective_base_url": probe["content"]["effective_base_url"],
                "checked_endpoint_ids": endpoint_ids,
                "available_count": available_count,
                "checked_count": len(probes),
                "readiness_level": _service_readiness_level(available_count, len(probes)),
                "probes": probes,
            }
        )
    return _result(
        "live_service_readiness_snapshot_result",
        {"service_ids": service_ids, "timeout_seconds": timeout_seconds},
        {
            "manifest_version": manifest["manifest_version"],
            "services": snapshots,
            "scope_note": manifest["scope_note"],
            "update_awareness": _update_awareness_for_components(
                [
                    str(service.get("component_id"))
                    for service in services
                    if isinstance(service.get("component_id"), str)
                ]
            ),
        },
    )


def _timeout_arg(arguments: dict[str, object], name: str) -> float:
    manifest = _load_live_services()
    default = float(manifest.get("default_timeout_seconds", 2.0))
    value = arguments.get(name)
    if value is None:
        return default
    if not isinstance(value, (int, float)) or value <= 0 or value > 30:
        raise InputError(f"Tool argument '{name}' must be a number between 0 and 30.")
    return float(value)


def _service_readiness_level(available_count: int, checked_count: int) -> str:
    if checked_count == 0:
        return "not_checked"
    if available_count == checked_count:
        return "reachable"
    if available_count > 0:
        return "partially_reachable"
    return "unreachable"


TOOL_DEFINITIONS = [
    {
        "name": "list_solution_capabilities",
        "title": "List CE-RISE Solution Capabilities",
        "description": "List deterministic assistant-facing CE-RISE capability families from the local catalog.",
        "inputSchema": _tool_input_schema(
            {
                "family": {
                    "type": "string",
                    "description": "Optional capability family filter, such as discovery, design, data-model, implementation, validation, or deployment.",
                }
            },
            [],
        ),
    },
    {
        "name": "list_solution_components",
        "title": "List CE-RISE Solution Components",
        "description": "List known existing CE-RISE components and their intended assistant reuse role.",
        "inputSchema": _tool_input_schema(
            {
                "kind": {
                    "type": "string",
                    "description": "Optional component kind filter.",
                },
                "capability_id": {
                    "type": "string",
                    "description": "Optional capability id used to return related components.",
                },
            },
            [],
        ),
    },
    {
        "name": "map_user_goal_to_ce_rise_capabilities",
        "title": "Map User Goal To CE-RISE Capabilities",
        "description": "Map a user goal to existing CE-RISE capabilities and suggested components using the deterministic local catalog.",
        "inputSchema": _tool_input_schema(
            {
                "user_goal": {
                    "type": "string",
                    "description": "User's Digital Passport engineering goal.",
                },
                "constraints": {
                    "type": "array",
                    "description": "Optional project constraints or keywords.",
                    "items": {"type": "string"},
                },
            },
            ["user_goal"],
        ),
    },
    {
        "name": "recommend_passport_architecture",
        "title": "Recommend Passport Architecture",
        "description": "Recommend a CE-RISE reuse-oriented Digital Passport architecture pattern.",
        "inputSchema": _tool_input_schema(
            {
                "use_case": {
                    "type": "string",
                    "description": "Digital Passport use case or implementation scenario.",
                },
                "priorities": {
                    "type": "array",
                    "description": "Optional priorities such as local validation, deployment, model alignment, or production preparation.",
                    "items": {"type": "string"},
                },
            },
            ["use_case"],
        ),
    },
    {
        "name": "generate_implementation_plan",
        "title": "Generate Implementation Plan",
        "description": "Generate an ordered implementation plan that reuses existing CE-RISE assets.",
        "inputSchema": _tool_input_schema(
            {
                "goal": {
                    "type": "string",
                    "description": "Implementation goal.",
                },
                "architecture_id": {
                    "type": "string",
                    "description": "Optional architecture pattern id from recommend_passport_architecture.",
                },
                "known_components": {
                    "type": "array",
                    "description": "Optional known CE-RISE component ids already selected.",
                    "items": {"type": "string"},
                },
            },
            ["goal"],
        ),
    },
    {
        "name": "assess_implementation_readiness",
        "title": "Assess Implementation Readiness",
        "description": "Assess whether a Digital Passport implementation context has enough information to proceed.",
        "inputSchema": _tool_input_schema(
            {
                "project_context": {
                    "type": "object",
                    "description": "Declared implementation context. Useful keys include passport_scope, user_goal, data_sources, selected_components, data_model_strategy, deployment_context, and validation_strategy.",
                    "additionalProperties": True,
                }
            },
            ["project_context"],
        ),
    },
    {
        "name": "assess_adoption_context",
        "title": "Assess Adoption Context",
        "description": "Assess a general Digital Passport adoption context across scope, drivers, value-chain role, shared information, data readiness, and value goals.",
        "inputSchema": _tool_input_schema(
            {
                "adoption_context": {
                    "type": "object",
                    "description": "Declared adoption context. Useful keys include organization_role, passport_scope, compliance_drivers, value_chain_actors, shared_information, data_sources, existing_systems, value_goals, and implementation_constraints.",
                    "additionalProperties": True,
                }
            },
            ["adoption_context"],
        ),
    },
    {
        "name": "map_value_chain_flows",
        "title": "Map Value-Chain Flows",
        "description": "Map requested, held, validated, enriched, or shared Digital Passport information across value-chain actors.",
        "inputSchema": _tool_input_schema(
            {
                "adoption_context": {
                    "type": "object",
                    "description": "Optional adoption context object.",
                    "additionalProperties": True,
                },
                "product_scope": {
                    "type": "string",
                    "description": "Optional product, material, asset, or process scope.",
                },
                "organization_role": {
                    "type": "string",
                    "description": "Optional organization role in the value chain.",
                },
                "value_chain_actors": {
                    "type": "array",
                    "description": "Optional list of value-chain actors.",
                    "items": {"type": "string"},
                },
                "information_needs": {
                    "type": "array",
                    "description": "Optional list of information needs or shared information types.",
                    "items": {"type": "string"},
                },
            },
            [],
        ),
    },
    {
        "name": "identify_value_opportunities",
        "title": "Identify Value Opportunities",
        "description": "Identify practical value opportunities from shared Digital Passport information.",
        "inputSchema": _tool_input_schema(
            {
                "adoption_context": {
                    "type": "object",
                    "description": "Optional adoption context object.",
                    "additionalProperties": True,
                },
                "shared_information": {
                    "type": "array",
                    "description": "Optional declared shared information types or examples.",
                    "items": {"type": "string"},
                },
                "value_goals": {
                    "type": "array",
                    "description": "Optional target value goals beyond compliance.",
                    "items": {"type": "string"},
                },
                "selected_flow_ids": {
                    "type": "array",
                    "description": "Optional flow ids from map_value_chain_flows.",
                    "items": {"type": "string"},
                },
            },
            [],
        ),
    },
    {
        "name": "recommend_adoption_path",
        "title": "Recommend Adoption Path",
        "description": "Recommend a CE-RISE reuse-oriented Digital Passport adoption path.",
        "inputSchema": _tool_input_schema(
            {
                "adoption_context": {
                    "type": "object",
                    "description": "Declared adoption context.",
                    "additionalProperties": True,
                },
                "priorities": {
                    "type": "array",
                    "description": "Optional priorities such as compliance, local prototype, model alignment, value-chain exchange, or deployment preparation.",
                    "items": {"type": "string"},
                },
            },
            ["adoption_context"],
        ),
    },
    {
        "name": "generate_implementation_roadmap",
        "title": "Generate Implementation Roadmap",
        "description": "Generate a phased roadmap for Digital Passport adoption and implementation over existing CE-RISE assets.",
        "inputSchema": _tool_input_schema(
            {
                "adoption_context": {
                    "type": "object",
                    "description": "Declared adoption context.",
                    "additionalProperties": True,
                },
                "adoption_path_id": {
                    "type": "string",
                    "description": "Optional adoption path id from recommend_adoption_path.",
                },
                "time_horizon": {
                    "type": "string",
                    "description": "Optional planning horizon label.",
                },
            },
            ["adoption_context"],
        ),
    },
    {
        "name": "list_deployment_artifact_templates",
        "title": "List Deployment Artifact Templates",
        "description": "List CE-RISE GitOps-template-derived deployment artifact profiles for Compose and Kubernetes outputs.",
        "inputSchema": _tool_input_schema(
            {
                "target": {
                    "type": "string",
                    "description": "Optional target filter: compose, kubernetes, or both.",
                },
            },
            [],
        ),
    },
    {
        "name": "generate_deployment_artifact_plan",
        "title": "Generate Deployment Artifact Plan",
        "description": "Map deployment choices to Compose/Kubernetes starter artifact profiles derived from the CE-RISE GitOps template.",
        "inputSchema": _tool_input_schema(
            {
                "target": {
                    "type": "string",
                    "description": "Optional deployment target: compose, kubernetes, or both. Defaults to both.",
                },
                "adoption_context": {
                    "type": "object",
                    "description": "Optional adoption or implementation context to carry through the plan.",
                    "additionalProperties": True,
                },
                "selected_components": {
                    "type": "array",
                    "description": "Optional CE-RISE component ids already selected.",
                    "items": {"type": "string"},
                },
                "include_re_indicators": {
                    "type": "boolean",
                    "description": "When true, include RE Indicators Calculation Service profiles/extensions.",
                },
                "include_internal_adapter": {
                    "type": "boolean",
                    "description": "When true, include the optional internal adapter Compose profile.",
                },
                "check_remote_updates": {
                    "type": "boolean",
                    "description": "When true, check configured update channels and include current metadata in the generated plan context.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds for update checks.",
                },
            },
            [],
        ),
    },
    {
        "name": "generate_deployment_artifacts",
        "title": "Generate Deployment Artifacts",
        "description": "Return Docker Compose and/or Kubernetes starter file contents derived from the existing CE-RISE GitOps template.",
        "inputSchema": _tool_input_schema(
            {
                "target": {
                    "type": "string",
                    "description": "Required deployment target: compose, kubernetes, or both.",
                },
                "project_name": {
                    "type": "string",
                    "description": "Optional project name used for generated Kubernetes namespaces and artifact ids.",
                },
                "environment": {
                    "type": "string",
                    "description": "Optional environment label: local, dev, or prod.",
                },
                "selected_components": {
                    "type": "array",
                    "description": "Optional CE-RISE component ids already selected.",
                    "items": {"type": "string"},
                },
                "include_re_indicators": {
                    "type": "boolean",
                    "description": "When true, include RE Indicators Calculation Service profiles/extensions.",
                },
                "include_internal_adapter": {
                    "type": "boolean",
                    "description": "When true, include the optional internal adapter Compose profile.",
                },
                "external_io_adapter_url": {
                    "type": "string",
                    "description": "Optional external HTTP IO adapter URL placeholder.",
                },
                "auth_mode": {
                    "type": "string",
                    "description": "Optional HEX Core authentication mode placeholder, such as jwt_jwks or none.",
                },
                "check_remote_updates": {
                    "type": "boolean",
                    "description": "When true, check configured update channels and use current metadata where it maps safely to generated artifact fields.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds for update checks.",
                },
            },
            ["target"],
        ),
    },
    {
        "name": "assess_deployment_artifact_readiness",
        "title": "Assess Deployment Artifact Readiness",
        "description": "Assess whether enough deployment context is declared before generated artifacts are treated as implementation-ready.",
        "inputSchema": _tool_input_schema(
            {
                "deployment_context": {
                    "type": "object",
                    "description": "Declared deployment context. Useful keys include target_runtime, selected_services, io_adapter_strategy, model_registry_strategy, auth_strategy, environment_overlays, and operational_checks.",
                    "additionalProperties": True,
                },
            },
            ["deployment_context"],
        ),
    },
    {
        "name": "list_reference_examples",
        "title": "List Reference Examples",
        "description": "List curated CE-RISE reference examples that can be generalized without copying their concrete demo data or local-only settings.",
        "inputSchema": _tool_input_schema(
            {
                "source_component_id": {
                    "type": "string",
                    "description": "Optional CE-RISE component id filter, such as dp_system_local_demonstrator.",
                },
            },
            [],
        ),
    },
    {
        "name": "generalize_reference_example",
        "title": "Generalize Reference Example",
        "description": "Generalize reusable workflow patterns from a CE-RISE reference example for a declared Digital Passport adoption context.",
        "inputSchema": _tool_input_schema(
            {
                "example_id": {
                    "type": "string",
                    "description": "Reference example id from list_reference_examples.",
                },
                "adoption_context": {
                    "type": "object",
                    "description": "Declared adoption context. Useful keys include organization_role, passport_scope, value_chain_actors, shared_information, and value_goals.",
                    "additionalProperties": True,
                },
                "target_outcome": {
                    "type": "string",
                    "description": "Optional target outcome, such as local learning workflow, deployment handover, or integration planning.",
                },
            },
            ["example_id"],
        ),
    },
    {
        "name": "list_update_channels",
        "title": "List Update Channels",
        "description": "List configured read-only CE-RISE repository, release, tag, documentation, and artifact update channels.",
        "inputSchema": _tool_input_schema(
            {
                "component_id": {
                    "type": "string",
                    "description": "Optional CE-RISE component id filter.",
                },
                "source_id": {
                    "type": "string",
                    "description": "Optional connected source id filter.",
                },
                "update_role": {
                    "type": "string",
                    "description": "Optional update role filter, such as software_component_version, model_artifact_version, deployment_template_version, reference_example_version, tooling_version, or documentation_availability.",
                },
            },
            [],
        ),
    },
    {
        "name": "check_update_channels",
        "title": "Check Update Channels",
        "description": "Fetch current metadata from configured read-only CE-RISE update channels.",
        "inputSchema": _tool_input_schema(
            {
                "channel_ids": {
                    "type": "array",
                    "description": "Optional update channel ids to check. Omit to select by component_ids or check all channels.",
                    "items": {"type": "string"},
                },
                "component_ids": {
                    "type": "array",
                    "description": "Optional CE-RISE component ids whose update channels should be checked.",
                    "items": {"type": "string"},
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds.",
                },
            },
            [],
        ),
    },
    {
        "name": "build_update_aware_solution_context",
        "title": "Build Update-Aware Solution Context",
        "description": "Combine stable catalog guidance with optional current release/tag/artifact metadata from configured CE-RISE update channels.",
        "inputSchema": _tool_input_schema(
            {
                "user_goal": {
                    "type": "string",
                    "description": "Optional user goal used to select relevant components from the stable catalog.",
                },
                "component_ids": {
                    "type": "array",
                    "description": "Optional CE-RISE component ids. When omitted, relevant components are selected from user_goal or all components are included.",
                    "items": {"type": "string"},
                },
                "check_remote": {
                    "type": "boolean",
                    "description": "When true, fetch current metadata from configured update channels.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds.",
                },
            },
            [],
        ),
    },
    {
        "name": "discover_model_repositories",
        "title": "Discover Model Repositories",
        "description": "Discover CE-RISE model repositories under the configured model namespace and propose update channels for newly available models.",
        "inputSchema": _tool_input_schema(
            {
                "check_remote": {
                    "type": "boolean",
                    "description": "When true, fetch the current CE-RISE-models repository list from the configured discovery channel. Defaults to true.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds.",
                },
            },
            [],
        ),
    },
    {
        "name": "list_connected_sources",
        "title": "List Connected CE-RISE Sources",
        "description": "List curated CE-RISE repositories, documentation sites, models, and service references connected to this assistant.",
        "inputSchema": _tool_input_schema(
            {
                "kind": {
                    "type": "string",
                    "description": "Optional source kind filter.",
                },
                "include_status": {
                    "type": "boolean",
                    "description": "When true, include local repository availability and key-file status.",
                },
            },
            [],
        ),
    },
    {
        "name": "check_connected_sources",
        "title": "Check Connected Sources",
        "description": "Check local and optionally remote availability for connected CE-RISE sources.",
        "inputSchema": _tool_input_schema(
            {
                "source_ids": {
                    "type": "array",
                    "description": "Optional list of source ids to check. Omit to check all sources.",
                    "items": {"type": "string"},
                },
                "check_remote": {
                    "type": "boolean",
                    "description": "When true, perform network HEAD checks for repository and documentation URLs.",
                },
            },
            [],
        ),
    },
    {
        "name": "inspect_connected_source",
        "title": "Inspect Connected Source",
        "description": "Inspect curated key files from one connected CE-RISE source, including Markdown headings when available.",
        "inputSchema": _tool_input_schema(
            {
                "source_id": {
                    "type": "string",
                    "description": "Connected source id from list_connected_sources.",
                },
                "include_headings": {
                    "type": "boolean",
                    "description": "When true, include Markdown headings discovered in key files.",
                },
            },
            ["source_id"],
        ),
    },
    {
        "name": "build_connected_solution_snapshot",
        "title": "Build Connected Solution Snapshot",
        "description": "Build a grounded snapshot connecting catalog components to curated CE-RISE source repositories and documentation.",
        "inputSchema": _tool_input_schema(
            {
                "source_ids": {
                    "type": "array",
                    "description": "Optional list of source ids. Omit to include all connected sources.",
                    "items": {"type": "string"},
                },
                "include_headings": {
                    "type": "boolean",
                    "description": "When true, include Markdown headings for each available key file.",
                },
            },
            [],
        ),
    },
    {
        "name": "list_live_service_connections",
        "title": "List Live Service Connections",
        "description": "List curated read-only live service discovery connections for CE-RISE services.",
        "inputSchema": _tool_input_schema(
            {
                "service_family": {
                    "type": "string",
                    "description": "Optional service family filter, such as core, storage, or calculation.",
                },
            },
            [],
        ),
    },
    {
        "name": "probe_live_service",
        "title": "Probe Live Service",
        "description": "Probe curated read-only GET endpoints for one live CE-RISE service connection.",
        "inputSchema": _tool_input_schema(
            {
                "service_id": {
                    "type": "string",
                    "description": "Service id from list_live_service_connections.",
                },
                "endpoint_ids": {
                    "type": "array",
                    "description": "Optional list of safe endpoint ids to probe. Omit to probe all safe endpoints for the service.",
                    "items": {"type": "string"},
                },
                "base_url": {
                    "type": "string",
                    "description": "Optional localhost-only base URL override for local testing.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds.",
                },
            },
            ["service_id"],
        ),
    },
    {
        "name": "inspect_live_service_openapi",
        "title": "Inspect Live Service OpenAPI",
        "description": "Fetch and summarize the OpenAPI document from one live CE-RISE service connection.",
        "inputSchema": _tool_input_schema(
            {
                "service_id": {
                    "type": "string",
                    "description": "Service id from list_live_service_connections.",
                },
                "base_url": {
                    "type": "string",
                    "description": "Optional localhost-only base URL override for local testing.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds.",
                },
            },
            ["service_id"],
        ),
    },
    {
        "name": "build_live_service_readiness_snapshot",
        "title": "Build Live Service Readiness Snapshot",
        "description": "Build a read-only reachability/readiness snapshot over curated CE-RISE live service connections.",
        "inputSchema": _tool_input_schema(
            {
                "service_ids": {
                    "type": "array",
                    "description": "Optional service ids from list_live_service_connections. Omit to check all services.",
                    "items": {"type": "string"},
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional HTTP timeout between 0 and 30 seconds.",
                },
            },
            [],
        ),
    },
]

TOOL_HANDLERS = {
    "list_solution_capabilities": list_solution_capabilities,
    "list_solution_components": list_solution_components,
    "map_user_goal_to_ce_rise_capabilities": map_user_goal_to_ce_rise_capabilities,
    "recommend_passport_architecture": recommend_passport_architecture,
    "generate_implementation_plan": generate_implementation_plan,
    "assess_implementation_readiness": assess_implementation_readiness,
    "assess_adoption_context": assess_adoption_context,
    "map_value_chain_flows": map_value_chain_flows,
    "identify_value_opportunities": identify_value_opportunities,
    "recommend_adoption_path": recommend_adoption_path,
    "generate_implementation_roadmap": generate_implementation_roadmap,
    "list_deployment_artifact_templates": list_deployment_artifact_templates,
    "generate_deployment_artifact_plan": generate_deployment_artifact_plan,
    "generate_deployment_artifacts": generate_deployment_artifacts,
    "assess_deployment_artifact_readiness": assess_deployment_artifact_readiness,
    "list_reference_examples": list_reference_examples,
    "generalize_reference_example": generalize_reference_example,
    "list_update_channels": list_update_channels,
    "check_update_channels": check_update_channels,
    "build_update_aware_solution_context": build_update_aware_solution_context,
    "discover_model_repositories": discover_model_repositories,
    "list_connected_sources": list_connected_sources,
    "check_connected_sources": check_connected_sources,
    "inspect_connected_source": inspect_connected_source,
    "build_connected_solution_snapshot": build_connected_solution_snapshot,
    "list_live_service_connections": list_live_service_connections,
    "probe_live_service": probe_live_service,
    "inspect_live_service_openapi": inspect_live_service_openapi,
    "build_live_service_readiness_snapshot": build_live_service_readiness_snapshot,
}

RESOURCE_DEFINITIONS = [
    {
        "uri": "ce-rise://solution/catalog",
        "name": "CE-RISE assistant solution catalog",
        "description": "Local deterministic catalog of CE-RISE capabilities, components, and architecture patterns used by this MCP server.",
        "mimeType": "application/json",
    },
    {
        "uri": "ce-rise://solution/scope",
        "name": "Assistant scope rule",
        "description": "Scope rule that this assistant guides reuse of existing CE-RISE assets and does not replace them.",
        "mimeType": "text/plain",
    },
    {
        "uri": "ce-rise://sources/manifest",
        "name": "Connected CE-RISE source manifest",
        "description": "Curated manifest of CE-RISE repositories, documentation sites, model assets, and service references connected to this MCP server.",
        "mimeType": "application/json",
    },
    {
        "uri": "ce-rise://services/live-connections",
        "name": "Live CE-RISE service connection manifest",
        "description": "Curated manifest of read-only live service discovery probes for CE-RISE services.",
        "mimeType": "application/json",
    },
    {
        "uri": "ce-rise://deployment/artifact-templates",
        "name": "Deployment artifact template manifest",
        "description": "Curated manifest of Compose and Kubernetes starter artifact profiles derived from the CE-RISE GitOps template.",
        "mimeType": "application/json",
    },
    {
        "uri": "ce-rise://examples/reference-generalization",
        "name": "Reference example generalization manifest",
        "description": "Curated manifest of CE-RISE reference examples and the reusable patterns that can be generalized from them.",
        "mimeType": "application/json",
    },
    {
        "uri": "ce-rise://updates/channels",
        "name": "Update channel manifest",
        "description": "Configured read-only CE-RISE repository, release, tag, documentation, and generated-artifact update channels.",
        "mimeType": "application/json",
    },
]


class McpServer:
    """Thin newline-delimited JSON-RPC stdio MCP server."""

    def __init__(self) -> None:
        self._has_initialized = False
        self._protocol_version = LATEST_PROTOCOL_VERSION

    def handle_message(self, payload: Any) -> list[dict[str, object]]:
        if isinstance(payload, list):
            responses: list[dict[str, object]] = []
            for item in payload:
                responses.extend(self.handle_message(item))
            return responses
        if not isinstance(payload, dict):
            return [self._error_response(None, JSONRPC_INVALID_REQUEST, "Request must be a JSON object.")]
        if "method" not in payload:
            return []

        method = payload["method"]
        request_id = payload.get("id")
        params = payload.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return [self._error_response(request_id, JSONRPC_INVALID_PARAMS, "Request params must be an object.")]

        if method == "initialize":
            return [self._handle_initialize(request_id, params)]
        if method == "notifications/initialized":
            return []
        if method == "ping":
            return [self._response(request_id, {})]
        if method == "tools/list":
            return [self._handle_tools_list(request_id)]
        if method == "tools/call":
            return [self._handle_tools_call(request_id, params)]
        if method == "resources/list":
            return [self._handle_resources_list(request_id)]
        if method == "resources/read":
            return [self._handle_resources_read(request_id, params)]
        return [self._error_response(request_id, JSONRPC_METHOD_NOT_FOUND, f"Unsupported method: {method}")]

    def _handle_initialize(self, request_id: object, params: dict[str, object]) -> dict[str, object]:
        if request_id is None:
            return self._error_response(None, JSONRPC_INVALID_REQUEST, "initialize must be a request.")
        requested_version = params.get("protocolVersion")
        if isinstance(requested_version, str) and requested_version in SUPPORTED_PROTOCOL_VERSIONS:
            self._protocol_version = requested_version
        else:
            self._protocol_version = LATEST_PROTOCOL_VERSION
        self._has_initialized = True
        return self._response(
            request_id,
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {
                    "name": "dp-engineering-assistant-mcp",
                    "title": "CE-RISE Digital Passport Engineering Assistant MCP Server",
                    "version": __version__,
                },
                "instructions": (
                    "Use this server to discover and combine existing CE-RISE assets for Digital Passport "
                    "engineering workflows. It guides reuse; it does not replace CE-RISE components."
                ),
            },
        )

    def _handle_tools_list(self, request_id: object) -> dict[str, object]:
        error = self._require_initialized(request_id)
        if error:
            return error
        return self._response(request_id, {"tools": TOOL_DEFINITIONS})

    def _handle_tools_call(self, request_id: object, params: dict[str, object]) -> dict[str, object]:
        error = self._require_initialized(request_id)
        if error:
            return error
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str):
            return self._error_response(request_id, JSONRPC_INVALID_PARAMS, "Tool name must be a string.")
        if not isinstance(arguments, dict):
            return self._error_response(request_id, JSONRPC_INVALID_PARAMS, "Tool arguments must be an object.")
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return self._error_response(request_id, JSONRPC_METHOD_NOT_FOUND, f"Unknown tool: {name}")
        try:
            result = handler(arguments)
            return self._response(request_id, self._tool_result(result, is_error=False))
        except AssistantError as exc:
            return self._response(request_id, self._tool_result(exc.to_result(), is_error=True))
        except Exception as exc:  # pragma: no cover
            error_result = {
                "result_type": "error_result",
                "error": {
                    "code": "internal_error",
                    "message": str(exc),
                    "details": [],
                },
            }
            return self._response(request_id, self._tool_result(error_result, is_error=True))

    def _handle_resources_list(self, request_id: object) -> dict[str, object]:
        error = self._require_initialized(request_id)
        if error:
            return error
        return self._response(request_id, {"resources": RESOURCE_DEFINITIONS})

    def _handle_resources_read(self, request_id: object, params: dict[str, object]) -> dict[str, object]:
        error = self._require_initialized(request_id)
        if error:
            return error
        uri = params.get("uri")
        if not isinstance(uri, str):
            return self._error_response(request_id, JSONRPC_INVALID_PARAMS, "Resource uri must be a string.")
        if uri == "ce-rise://solution/catalog":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_dumps(_load_catalog()),
                        }
                    ]
                },
            )
        if uri == "ce-rise://solution/scope":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": (
                                "The CE-RISE Digital Passport Engineering Assistant helps users make the most "
                                "of existing CE-RISE components, services, schemas, documentation, methods, and "
                                "deployment workflows. It must not substitute, replace, or bypass them."
                            ),
                        }
                    ]
                },
            )
        if uri == "ce-rise://sources/manifest":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_dumps(_load_sources()),
                        }
                    ]
                },
            )
        if uri == "ce-rise://services/live-connections":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_dumps(_load_live_services()),
                        }
                    ]
                },
            )
        if uri == "ce-rise://deployment/artifact-templates":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_dumps(_load_deployment_artifacts()),
                        }
                    ]
                },
            )
        if uri == "ce-rise://examples/reference-generalization":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_dumps(_load_reference_examples()),
                        }
                    ]
                },
            )
        if uri == "ce-rise://updates/channels":
            return self._response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": _json_dumps(_load_update_channels()),
                        }
                    ]
                },
            )
        return self._error_response(request_id, JSONRPC_INVALID_PARAMS, f"Unknown resource uri: {uri}")

    def _require_initialized(self, request_id: object) -> dict[str, object] | None:
        if self._has_initialized:
            return None
        return self._error_response(
            request_id,
            JSONRPC_INVALID_REQUEST,
            "The client must send initialize before calling other MCP methods.",
        )

    def _tool_result(self, result: dict[str, object], is_error: bool) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": _json_dumps(result),
                }
            ],
            "structuredContent": result,
            "isError": is_error,
        }

    def _response(self, request_id: object, result: dict[str, object]) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    def _error_response(self, request_id: object, code: int, message: str) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


def run_stdio_server() -> int:
    server = McpServer()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            response = server._error_response(None, JSONRPC_INVALID_REQUEST, "Input line is not valid JSON.")
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
            continue
        for response in server.handle_message(payload):
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


def main() -> int:
    return run_stdio_server()


if __name__ == "__main__":
    raise SystemExit(main())
