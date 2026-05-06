# CE-RISE Digital Passport Engineering Assistant

[![DOI](https://zenodo.org/badge/DOI/TOBEOBTAINED.svg)](https://doi.org/TOBEOBTAINED)

<!-- mcp-name: io.github.CE-RISE-software/dp-engineering-assistant -->

A repo-native stdio MCP server that helps AI agents and human users make better use of existing CE-RISE Digital Passport components, services, schemas, documentation, and deployment workflows.

This assistant is not a replacement for CE-RISE assets. Its role is to guide discovery, configuration, implementation planning, readiness checks, and appropriate reuse of the existing CE-RISE ecosystem.

The main workflow is general Digital Passport adoption: helping an organization understand compliance drivers, value-chain information flows, implementation readiness, and value opportunities from shared information, regardless of company size or organizational label.

The main human-facing CE-RISE solution entry point is:

- https://solution.ce-rise.eu/

---

## What this repository contains

- A minimal stdio MCP server in `server/mcp_server.py`
- A deterministic initial CE-RISE capability and component catalog in `data/solution_catalog.json`
- A curated connected-source manifest in `data/connected_sources.json`
- A read-only live service connection manifest in `data/live_service_connections.json`
- A deployment artifact manifest in `data/deployment_artifacts.json`
- A reference-example generalization manifest in `data/reference_examples.json`
- An update channel manifest in `data/update_channels.json`
- MCP registry metadata in `server.json`
- A container runtime skeleton in `Dockerfile`
- Local run, smoke, and validation scripts in `scripts/`
- A first deterministic design workflow example in `examples/01-design-workflow/`
- Documentation in `docs` using [Book](https://book.deno.land/)
- GitHub mirror automation for release, OCI image publication, and MCP registry publication
- Codeberg Pages automation for the documentation site

The server is intentionally repo-native at this stage. It does not introduce an installable Python package.

## MCP Tool Shape

The initial tool surface is catalog-backed and deterministic:

- `list_solution_capabilities`
- `list_solution_components`
- `map_user_goal_to_ce_rise_capabilities`
- `recommend_passport_architecture`
- `generate_implementation_plan`
- `assess_implementation_readiness`
- `assess_adoption_context`
- `map_value_chain_flows`
- `identify_value_opportunities`
- `recommend_adoption_path`
- `generate_implementation_roadmap`
- `list_deployment_artifact_templates`
- `generate_deployment_artifact_plan`
- `generate_deployment_artifacts`
- `assess_deployment_artifact_readiness`
- `list_reference_examples`
- `generalize_reference_example`
- `list_update_channels`
- `check_update_channels`
- `build_update_aware_solution_context`
- `discover_model_repositories`
- `list_connected_sources`
- `check_connected_sources`
- `inspect_connected_source`
- `build_connected_solution_snapshot`
- `list_live_service_connections`
- `probe_live_service`
- `inspect_live_service_openapi`
- `build_live_service_readiness_snapshot`

The initial resource surface is:

- `ce-rise://solution/catalog`
- `ce-rise://solution/scope`
- `ce-rise://sources/manifest`
- `ce-rise://services/live-connections`
- `ce-rise://deployment/artifact-templates`
- `ce-rise://examples/reference-generalization`
- `ce-rise://updates/channels`

The first implementation is documentation/resource-oriented with a small read-only service discovery layer, a deployment-artifact output layer, a reference-example generalization layer, and an optional update-awareness layer. It connects to curated CE-RISE repositories and documentation references, can inspect local sibling repositories when they are available, can optionally check remote repository/documentation URL availability, can probe read-only live service endpoints such as health, readiness, version, and OpenAPI, can return Docker Compose or Kubernetes starter file contents derived from the existing CE-RISE GitOps template, can generalize reusable patterns from the local demonstrator without copying its concrete demo data or local-only settings, and can check configured release/tag/documentation channels for current upstream metadata when requested.

Normal component-aware outputs include an `update_awareness` field. This makes update needs visible even when the user did not explicitly ask about versions: the field lists relevant configured update channels and recommends the update-aware tools before implementation, deployment, or detailed technical decisions.

Generation tools can carry update context directly. For example, `generate_deployment_artifacts` accepts `check_remote_updates`; when enabled, it checks configured update channels, includes `version_context`, writes a generated `VERSION-CONTEXT.md` file into the returned artifact set, and uses checked `model_artifact_version` tags where they map safely to generated registry catalog entries.

The update layer covers software components, reference examples, deployment templates, documentation availability, and known data model repositories through explicit read-only channels. The server can also discover additional CE-RISE model repositories under the configured model namespace with `discover_model_repositories`; newly discovered repositories are returned as candidate update channels for review instead of being silently trusted as implementation inputs. Template and model-architecture repositories can be tracked for version awareness without being treated as deployable data model artifacts.

It does not call live CE-RISE business operations such as record creation, validation, query, indicator computation, or registry refresh.

Adoption, architecture, value-chain, and roadmap outputs include `source_references` and `live_service_connections` fields where relevant, so recommendations are grounded in CE-RISE assets rather than presented as standalone advice.

Deployment artifact outputs are starter planning artifacts only. They do not replace the canonical `dp-system-gitops-template` repository or the component-specific deployment documentation.

Compliance-oriented outputs are planning aids only. They do not provide legal certification or legal advice.

## Local Use

Run the MCP server:

```bash
./scripts/run-local.sh
```

Run a local MCP smoke check:

```bash
./scripts/smoke-mcp.sh
```

Run a container MCP smoke check:

```bash
./scripts/smoke-container.sh
```

Run local validation:

```bash
./scripts/validate-local.sh
```

Equivalent make targets are available:

```bash
make smoke
make smoke-container
make test
make validate
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

## Publication Model

Development happens on Codeberg:

- https://codeberg.org/CE-RISE-software/dp-engineering-assistant

The GitHub repository is a mirror used for release-side automation, following the same CE-RISE MCP publication pattern used by `dp-assessment-workbench`:

- build and publish the MCP OCI image to GitHub Container Registry;
- update `server.json` for the release version and image tag;
- publish the MCP server metadata to the official MCP Registry using GitHub OIDC;
- create GitHub releases for Zenodo integration.

The MCP registry identity is:

- `io.github.CE-RISE-software/dp-engineering-assistant`

The OCI image pattern is:

- `ghcr.io/ce-rise-software/dp-engineering-assistant-mcp:<release-version>`

## License

Licensed under the [European Union Public Licence v1.2 (EUPL-1.2)](LICENSE).

## Contributing

This repository is maintained on [Codeberg](https://codeberg.org/CE-RISE-software/dp-engineering-assistant) as the canonical source of truth. The GitHub repository is a read mirror used for release archival, OCI image publication, MCP registry publication, and Zenodo integration. Issues and pull requests should be opened on Codeberg.

---

<a href="https://europa.eu" target="_blank" rel="noopener noreferrer">
  <img src="https://ce-rise.eu/wp-content/uploads/2023/01/EN-Funded-by-the-EU-PANTONE-e1663585234561-1-1.png" alt="EU emblem" width="200"/>
</a>

Funded by the European Union under Grant Agreement No. 101092281 - CE-RISE.

Views and opinions expressed are those of the author(s) only and do not necessarily reflect those of the European Union or the granting authority (HADEA).
Neither the European Union nor the granting authority can be held responsible for them.

(c) 2026 CE-RISE consortium.

Licensed under the [European Union Public Licence v1.2 (EUPL-1.2)](LICENSE).

Attribution: CE-RISE project (Grant Agreement No. 101092281) and the individual authors/partners as indicated.

<a href="https://www.nilu.com" target="_blank" rel="noopener noreferrer">
  <img src="https://nilu.no/wp-content/uploads/2023/12/nilu-logo-seagreen-rgb-300px.png" alt="NILU logo" height="20"/>
</a>

Developed by NILU (Riccardo Boero - ribo@nilu.no) within the CE-RISE project.
