# MCP Server

The repository ships a thin stdio MCP server in `server/mcp_server.py`.

## Design Rule

The server is an assistant over existing CE-RISE assets. It must guide discovery, configuration, planning, and readiness assessment without substituting for CE-RISE components.

The current runtime is repo-native and uses only the Python standard library. It is not packaged as an installable Python project.

## Runtime Shape

- local entry point: `./scripts/run-local.sh`
- transport: stdio
- message framing: newline-delimited JSON-RPC 2.0
- exposed MCP capabilities: `tools`, `resources`
- catalog source: `data/solution_catalog.json`
- deployment artifact source: `data/deployment_artifacts.json`
- reference example source: `data/reference_examples.json`
- update channel source: `data/update_channels.json`

## Tools

| MCP tool | Result type | Purpose |
| --- | --- | --- |
| `list_solution_capabilities` | `solution_capabilities_result` | List CE-RISE capability families from the local catalog. |
| `list_solution_components` | `solution_components_result` | List existing CE-RISE components and assistant reuse roles. |
| `map_user_goal_to_ce_rise_capabilities` | `goal_mapping_result` | Map a user goal to CE-RISE capabilities and suggested components. |
| `recommend_passport_architecture` | `passport_architecture_recommendation_result` | Recommend a reuse-oriented Digital Passport architecture pattern. |
| `generate_implementation_plan` | `implementation_plan_result` | Generate ordered implementation steps over existing CE-RISE assets. |
| `assess_implementation_readiness` | `implementation_readiness_result` | Check whether enough project context is available to proceed. |
| `assess_adoption_context` | `adoption_context_assessment_result` | Assess scope, drivers, value-chain role, shared information, data readiness, and value goals. |
| `map_value_chain_flows` | `value_chain_flow_mapping_result` | Map Digital Passport information flows across value-chain actors. |
| `identify_value_opportunities` | `shared_information_value_opportunities_result` | Identify practical value opportunities from shared passport information. |
| `recommend_adoption_path` | `adoption_path_recommendation_result` | Recommend a general CE-RISE reuse-oriented adoption path. |
| `generate_implementation_roadmap` | `implementation_roadmap_result` | Generate a phased adoption and implementation roadmap. |
| `list_deployment_artifact_templates` | `deployment_artifact_templates_result` | List Compose/Kubernetes starter artifact profiles derived from the CE-RISE GitOps template. |
| `generate_deployment_artifact_plan` | `deployment_artifact_plan_result` | Map deployment choices to recommended artifact profiles and files. |
| `generate_deployment_artifacts` | `deployment_artifact_generation_result` | Return Docker Compose and/or Kubernetes starter file contents, with optional checked version context. |
| `assess_deployment_artifact_readiness` | `deployment_artifact_readiness_result` | Check whether deployment decisions are complete enough before using generated artifacts. |
| `list_reference_examples` | `reference_examples_result` | List curated CE-RISE examples that can be generalized. |
| `generalize_reference_example` | `reference_example_generalization_result` | Extract reusable workflow patterns from a reference example for a declared context. |
| `list_update_channels` | `update_channels_result` | List configured read-only update channels. |
| `check_update_channels` | `update_channel_check_result` | Fetch current metadata from configured repository, release, tag, documentation, or artifact channels. |
| `build_update_aware_solution_context` | `update_aware_solution_context_result` | Combine stable catalog guidance with optional current upstream metadata. |
| `discover_model_repositories` | `model_repository_discovery_result` | Discover CE-RISE model repositories under the configured namespace and propose update channels for newly available models. |
| `list_connected_sources` | `connected_sources_result` | List curated CE-RISE repositories, documentation sites, model assets, and service references. |
| `check_connected_sources` | `connected_source_availability_result` | Check local and optionally remote availability for connected CE-RISE sources. |
| `inspect_connected_source` | `connected_source_inspection_result` | Inspect curated key files from one connected CE-RISE source. |
| `build_connected_solution_snapshot` | `connected_solution_snapshot_result` | Build a source-grounded snapshot linking catalog components to connected sources. |
| `list_live_service_connections` | `live_service_connections_result` | List curated read-only live service discovery connections. |
| `probe_live_service` | `live_service_probe_result` | Probe curated read-only GET endpoints for one live service connection. |
| `inspect_live_service_openapi` | `live_service_openapi_inspection_result` | Fetch and summarize a live service OpenAPI document. |
| `build_live_service_readiness_snapshot` | `live_service_readiness_snapshot_result` | Build a read-only reachability/readiness snapshot across live service connections. |

## Resources

| URI | Purpose |
| --- | --- |
| `ce-rise://solution/catalog` | Exposes the deterministic local CE-RISE capability catalog. |
| `ce-rise://solution/scope` | Exposes the core non-substitution scope rule. |
| `ce-rise://sources/manifest` | Exposes the connected CE-RISE source manifest. |
| `ce-rise://services/live-connections` | Exposes the read-only live service connection manifest. |
| `ce-rise://deployment/artifact-templates` | Exposes the deployment artifact template manifest. |
| `ce-rise://examples/reference-generalization` | Exposes the reference-example generalization manifest. |
| `ce-rise://updates/channels` | Exposes the update channel manifest. |

## Result Contract

Tool results use a deterministic envelope:

- `result_type`
- `inputs`
- `content`
- `diagnostics`

MCP tool responses include the same payload in both `content[0].text` and `structuredContent`.

Compliance-oriented outputs are planning aids only. They do not provide legal certification or legal advice.

Adoption, value-chain, architecture, and roadmap tools include grounding fields where relevant:

- `source_references`: curated CE-RISE repositories, documentation sites, and model assets related to the recommendation;
- `live_service_connections`: read-only service discovery connections related to the selected components.

## Connected Sources

The connection layer is curated through `data/connected_sources.json`.

The server can:

- list connected CE-RISE repositories, documentation sites, model assets, and service references;
- inspect local sibling repositories when they are available in the same workspace;
- extract Markdown headings from curated key files;
- check remote repository and documentation URLs when `check_remote` is explicitly enabled.

It does not automatically call live CE-RISE business services in this first connected version.

## Reference Examples

The reference-example layer is curated through `data/reference_examples.json`.

The local demonstrator is treated as an illustrative workflow. The server can generalize reusable patterns from it, such as scope declaration, service selection, registry adaptation, representative payload design, lifecycle operations, and operational checks.

The server should not treat demonstrator-specific products, payloads, no-auth settings, ports, or local persistence decisions as defaults for other adopters.

## Update Awareness

The update-awareness layer is curated through `data/update_channels.json`.

Stable tools remain deterministic by default, but component-aware outputs include an `update_awareness` block so users are not expected to know on their own when upstream changes may matter. When current upstream metadata is needed, clients can call:

- `list_update_channels` to discover configured release, tag, documentation, and artifact channels;
- `check_update_channels` to fetch current metadata from selected channels;
- `build_update_aware_solution_context` to combine stable catalog components with optional remote update checks.
- `discover_model_repositories` to check the configured CE-RISE model repository namespace and propose channels for model repositories that are not yet explicitly tracked.

Generation tools can also include update checks directly when they expose `check_remote_updates`. In that mode, generated outputs include `version_context` and a generated `VERSION-CONTEXT.md` file.

This avoids needing a new MCP server release for every upstream model, component, or example update. It also keeps network access explicit instead of making every planning call depend on remote availability.

Discovered model repositories are treated as candidates. A generated artifact should only use a model version after an explicit model tag channel exists and has been checked.

## Deployment Artifact Outputs

The deployment artifact layer is curated through `data/deployment_artifacts.json`.

The server can return starter file contents for:

- Docker Compose baseline with HEX Core Service, a local registry catalog, and an external IO adapter URL;
- optional Compose profiles for the internal adapter and RE Indicators Calculation Service;
- Kubernetes base, development overlay, production overlay, and optional RE indicators extension.

The generated outputs are intended for planning, review, and handover into the canonical `dp-system-gitops-template` workflow. The server does not write files to disk and does not deploy anything.

Users must still review secrets, image tags, domains, registry entries, authentication mode, resource settings, and environment overlays against the existing CE-RISE template and component documentation.

## Live Service Discovery

The live service layer is curated through `data/live_service_connections.json`.

The server can probe:

- HEX Core Service: `GET /admin/health`, `GET /admin/ready`, `GET /admin/version`, `GET /admin/models/count`, `GET /openapi.json`
- Digital Passport JSON DB Storage Service: `GET /health`, `GET /ready`, `GET /openapi.json`
- RE Indicators Calculation Service: `GET /health`, `GET /openapi.json`

The server intentionally does not call write or domain-operation endpoints such as:

- record creation or query;
- model validation, create, or query operations;
- indicator computation;
- registry refresh.

Local URL overrides are restricted to localhost addresses.

## Local Use

```bash
./scripts/run-local.sh
./scripts/smoke-mcp.sh
./scripts/smoke-container.sh
./scripts/validate-local.sh
```

Minimal local MCP client configuration:

```json
{
  "mcpServers": {
    "dp-engineering-assistant": {
      "command": "/home/riccardo/code/CE-RISE-software/dp-engineering-assistant/scripts/run-local.sh"
    }
  }
}
```

## Publication

The MCP registry identity is declared in `server.json`:

- `io.github.CE-RISE-software/dp-engineering-assistant`

The GitHub mirror workflow `.github/workflows/publish-mcp.yml` is responsible for:

- validating the local server;
- updating `server.json` for the release version;
- building and pushing `ghcr.io/ce-rise-software/dp-engineering-assistant-mcp:<release-version>`;
- publishing the server metadata to the MCP Registry using GitHub OIDC.
