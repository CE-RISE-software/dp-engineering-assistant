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
  | "$RUNTIME" run -i --rm "$IMAGE" >/tmp/dp-engineering-assistant-container-smoke.jsonl

python -c 'import json, sys
with open("/tmp/dp-engineering-assistant-container-smoke.jsonl", encoding="utf-8") as handle:
    lines = [line for line in handle if line.strip()]
if len(lines) != 3:
    raise SystemExit(f"expected 3 JSON-RPC responses, got {len(lines)}")
for line in lines:
    item = json.loads(line)
    if "error" in item:
        raise SystemExit(json.dumps(item["error"]))
'
