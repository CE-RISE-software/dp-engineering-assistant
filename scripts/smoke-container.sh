#!/usr/bin/env bash
set -eu

IMAGE="${MCP_IMAGE:-dp-engineering-assistant-mcp:local}"

if [ -n "${CONTAINER_RUNTIME:-}" ]; then
  RUNTIME="$CONTAINER_RUNTIME"
elif command -v podman >/dev/null 2>&1; then
  RUNTIME="podman"
elif command -v docker >/dev/null 2>&1; then
  RUNTIME="docker"
else
  printf '%s\n' "No container runtime found. Install podman or docker, or set CONTAINER_RUNTIME." >&2
  exit 1
fi

"$RUNTIME" build -t "$IMAGE" .

printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"container-smoke","version":"0.0.0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"generate_deployment_artifacts","arguments":{"target":"compose","project_name":"container smoke","selected_components":["hex_core_service"],"check_remote_updates":false}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"review_configuration_consistency","arguments":{"target":"compose","files":[{"path":"compose.yaml","content":"services:\n  see-impacts-calculation-service:\n    environment:\n      HEX_CORE_BASE_URL: http://localhost:8080\n"}]}}}' \
  '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"generate_deployment_artifacts","arguments":{"target":"compose","selected_components":["see_impacts_calculation_service","external-analytics"],"hex_core_base_url":"https://validation.example.org"}}}' \
  | "$RUNTIME" run -i --rm "$IMAGE" >/tmp/dp-engineering-assistant-container-smoke.jsonl

python -c 'import json, sys
with open("/tmp/dp-engineering-assistant-container-smoke.jsonl", encoding="utf-8") as handle:
    lines = [line for line in handle if line.strip()]
if len(lines) != 5:
    raise SystemExit(f"expected 5 JSON-RPC responses, got {len(lines)}")
for line in lines:
    item = json.loads(line)
    if "error" in item:
        raise SystemExit(json.dumps(item["error"]))
    if item.get("result", {}).get("isError"):
        raise SystemExit("MCP tool returned an error")
review = json.loads(lines[-2])["result"]["structuredContent"]["content"]
if review["status"] != "inconsistent" or not any(item["code"] == "container_localhost_core" for item in review["findings"]):
    raise SystemExit("configuration review did not detect the container URL mismatch")
generation = json.loads(lines[-1])["result"]["structuredContent"]
if generation["inputs"]["include_core"] or generation["content"]["outside_generation_scope"] != ["external-analytics"]:
    raise SystemExit("mixed selection did not preserve the requested component boundary")
if any(item["path"] == "compose/registry/catalog.json" for item in generation["content"]["files"]):
    raise SystemExit("standalone SEE generation added an unselected core registry")
'
