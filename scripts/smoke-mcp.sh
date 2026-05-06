#!/usr/bin/env bash
set -eu

printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"local-smoke","version":"0.0.0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_solution_capabilities","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"assess_adoption_context","arguments":{"adoption_context":{"organization_role":"manufacturer","passport_scope":"product family","compliance_drivers":["customer reporting request"],"shared_information":["composition","traceability evidence"],"value_goals":["reduce reporting effort","support circularity"]}}}}' \
  '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"list_connected_sources","arguments":{"include_status":true}}}' \
  '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"list_live_service_connections","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"list_deployment_artifact_templates","arguments":{"target":"both"}}}' \
  '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"generate_deployment_artifact_plan","arguments":{"target":"both","selected_components":["hex_core_service","re_indicators_calculation_service"],"include_re_indicators":true}}}' \
  '{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"generalize_reference_example","arguments":{"example_id":"dp_system_local_demonstrator","target_outcome":"local learning workflow","adoption_context":{"organization_role":"manufacturer","passport_scope":"product family","value_chain_actors":["supplier","customer"],"shared_information":["composition","traceability evidence"]}}}}' \
  '{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"build_update_aware_solution_context","arguments":{"component_ids":["hex_core_service","ce_rise_models"],"check_remote":false}}}' \
  '{"jsonrpc":"2.0","id":11,"method":"tools/call","params":{"name":"discover_model_repositories","arguments":{"check_remote":false}}}' \
  | python server/mcp_server.py
