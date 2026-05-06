#!/usr/bin/env bash
set -eu

python -m json.tool data/solution_catalog.json >/dev/null
python -m json.tool data/connected_sources.json >/dev/null
python -m json.tool data/live_service_connections.json >/dev/null
python -m json.tool data/deployment_artifacts.json >/dev/null
python -m json.tool data/reference_examples.json >/dev/null
python -m json.tool data/update_channels.json >/dev/null
python -m json.tool server.json >/dev/null
python -m json.tool examples/03-update-aware-generation/request.json >/dev/null
python -m json.tool examples/03-update-aware-generation/expected-shape.json >/dev/null
python -m unittest discover -s tests -v
./scripts/smoke-mcp.sh >/tmp/dp-engineering-assistant-smoke.jsonl
