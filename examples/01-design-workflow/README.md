# Digital Passport Adoption Workflow Example

This example sketches one MCP-driven Digital Passport adoption workflow.

Scenario:

- an organization wants to explore a Digital Passport for a product, material, or asset family;
- compliance and customer reporting are important drivers;
- the organization also wants to reduce repeated reporting effort and support circularity-oriented information exchange;
- the workflow should reuse existing CE-RISE assets.

Run the local smoke check first:

```bash
./scripts/smoke-mcp.sh
```

Then call the server from an MCP client using these tools in order:

1. `list_connected_sources`
2. `list_live_service_connections`
3. `assess_adoption_context`
4. `map_value_chain_flows`
5. `identify_value_opportunities`
6. `recommend_adoption_path`
7. `generate_implementation_roadmap`
8. `generalize_reference_example`
9. `build_update_aware_solution_context`
10. `generate_deployment_artifact_plan`
11. `generate_deployment_artifacts`
12. `inspect_connected_source`
13. `build_live_service_readiness_snapshot`
14. `assess_implementation_readiness`

Example connected-source request:

```json
{
  "include_status": true
}
```

Example live service connection request:

```json
{}
```

Example adoption context:

```json
{
  "adoption_context": {
    "organization_role": "manufacturer",
    "passport_scope": "product family",
    "compliance_drivers": ["customer reporting request", "regulatory reporting preparation"],
    "value_chain_actors": ["supplier", "manufacturer", "customer", "repair partner", "recycler"],
    "shared_information": ["product identity", "material composition", "traceability evidence", "repair and end-of-life information"],
    "data_sources": ["ERP exports", "supplier declarations", "quality records"],
    "existing_systems": ["ERP", "spreadsheets", "supplier portal"],
    "value_goals": ["reduce repeated reporting", "improve supplier-customer exchange", "support circularity services"],
    "implementation_constraints": ["limited integration capacity", "need a local prototype first"]
  }
}
```

Example value-chain flow request:

```json
{
  "product_scope": "product family",
  "organization_role": "manufacturer",
  "value_chain_actors": ["supplier", "customer", "repair partner", "recycler"],
  "information_needs": ["composition", "provenance", "compliance evidence", "repair and end-of-life data"]
}
```

Example value opportunity request:

```json
{
  "shared_information": ["composition", "provenance", "compliance evidence", "repair and end-of-life data"],
  "value_goals": ["reduce reporting effort", "support circularity", "improve traceability confidence"],
  "selected_flow_ids": ["material_and_composition", "provenance_and_lifecycle_events", "compliance_evidence", "service_repair_reuse_end_of_life"]
}
```

Example roadmap request:

```json
{
  "adoption_path_id": "value_chain_exchange_path",
  "time_horizon": "first pilot",
  "adoption_context": {
    "organization_role": "manufacturer",
    "passport_scope": "product family",
    "shared_information": ["supplier composition", "traceability evidence", "repair and end-of-life information"]
  }
}
```

Example deployment artifact plan:

```json
{
  "target": "both",
  "selected_components": ["hex_core_service", "re_indicators_calculation_service"],
  "include_re_indicators": true,
  "adoption_context": {
    "organization_role": "manufacturer",
    "passport_scope": "product family",
    "shared_information": ["supplier composition", "traceability evidence"]
  }
}
```

Example reference-example generalization request:

```json
{
  "example_id": "dp_system_local_demonstrator",
  "target_outcome": "local learning workflow before deployment planning",
  "adoption_context": {
    "organization_role": "manufacturer",
    "passport_scope": "product family",
    "value_chain_actors": ["supplier", "customer", "repair partner", "recycler"],
    "shared_information": ["composition", "traceability evidence", "repair and end-of-life information"]
  }
}
```

Example update-aware context request:

```json
{
  "component_ids": ["hex_core_service", "ce_rise_models", "dp_system_gitops_template"],
  "check_remote": false
}
```

Set `check_remote` to `true` when the client should fetch current release, tag, documentation, and artifact metadata from configured CE-RISE channels.

Other workflow tools also return an `update_awareness` field when selected components, services, models, examples, or deployment templates may be affected by upstream changes. Treat that field as a prompt to run the update-aware step before implementation or deployment decisions.

Example deployment artifact generation request:

```json
{
  "target": "kubernetes",
  "project_name": "digital passport pilot",
  "include_re_indicators": true,
  "external_io_adapter_url": "https://io-adapter.example.org",
  "check_remote_updates": true
}
```

When `check_remote_updates` is enabled, the generated artifact set includes `VERSION-CONTEXT.md`, and registry catalog entries use checked model tags when they map cleanly to CE-RISE model artifact URLs.

Example connected-source inspection:

```json
{
  "source_id": "dp_assessment_workbench",
  "include_headings": true
}
```

Example read-only live service readiness request:

```json
{
  "service_ids": [
    "hex_core_service_local",
    "dp_storage_jsondb_service_local",
    "re_indicators_calculation_service_local"
  ],
  "timeout_seconds": 2
}
```

Expected behavior:

- the assistant keeps the workflow general and does not depend on company size labels;
- compliance-related output is framed as planning guidance, not legal certification;
- value-chain flows identify information to request, hold, validate, enrich, and share;
- value opportunities connect shared information to concrete business and circularity benefits;
- the roadmap points to existing CE-RISE assets instead of inventing replacements.
- connected-source tools ground recommendations in CE-RISE repositories and documentation references.
- live service tools only probe health, readiness, version, and OpenAPI endpoints.
- reference-example tools generalize from the local demonstrator without copying its fictional payloads or local-only settings.
- update-aware tools keep stable guidance local while optionally checking current upstream metadata.
- deployment artifact tools return starter Compose/Kubernetes file contents derived from the CE-RISE GitOps template, not a parallel deployment framework.
