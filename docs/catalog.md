# Solution Catalog

The initial MCP server is backed by `data/solution_catalog.json`.

The catalog is deliberately small and deterministic. It is not a source of truth replacing CE-RISE documentation or services. It is an assistant-facing routing layer that helps agents point users toward existing CE-RISE assets.

The connected-source layer is backed by `data/connected_sources.json`. It records curated links to CE-RISE repositories, documentation sites, model assets, and service references that ground the assistant's guidance.

The live service discovery layer is backed by `data/live_service_connections.json`. It records read-only GET probes for health, readiness, version, and OpenAPI discovery.

The deployment artifact layer is backed by `data/deployment_artifacts.json`. It records Compose and Kubernetes starter artifact profiles derived from the existing CE-RISE GitOps deployment template.

The reference-example layer is backed by `data/reference_examples.json`. It records illustrative CE-RISE workflows and the reusable patterns that can be generalized from them.

The update-awareness layer is backed by `data/update_channels.json`. It records read-only release, tag, repository-discovery, documentation, and generated-artifact metadata channels that can be checked at tool-call time.

## Catalog Sections

- `capabilities`: assistant-facing CE-RISE capability families.
- `components`: existing CE-RISE assets and their intended reuse role.
- `architecture_patterns`: reusable Digital Passport implementation paths.
- `adoption_context_fields`: fields used to assess general Digital Passport adoption context.
- `compliance_drivers`: broad planning drivers for compliance-oriented adoption, without legal certification.
- `value_chain_flow_types`: information flow categories across value-chain actors.
- `value_opportunity_patterns`: practical value opportunities from shared information.
- `adoption_paths`: phased CE-RISE reuse paths for adoption workflows.
- `readiness_fields`: fields used by readiness assessment.
- `deployment_artifacts`: generated through a separate manifest for Compose/Kubernetes artifact profiles and readiness fields.
- `reference_examples`: generated through a separate manifest for illustrative examples, reusable patterns, non-assumptions, and adaptation questions.
- `update_channels`: generated through a separate manifest for version-sensitive upstream metadata checks.

## Current Component Coverage

The initial catalog includes:

- CE-RISE Solution Portal
- HEX Core Service
- Digital Passport JSON DB Storage Service
- Digital Passport System Local Demonstrator
- Digital Passport System GitOps Template
- Digital Passport Model Assessment Workbench
- CE-RISE Models
- RE Indicators Calculation Service

This list is expected to grow as the server is connected to more detailed CE-RISE documentation and workflows.

## Maintenance Rule

Catalog entries should stay factual, conservative, and reuse-oriented. When a workflow needs implementation detail, the assistant should point to the relevant CE-RISE component or documentation rather than duplicating or replacing it.

Adoption and compliance entries should remain general planning guidance. They should not assert legal compliance or imply certification.

Connected-source entries should stay curated and explicit. The assistant should only inspect listed files from listed sources, and live service calls should be introduced separately with clear scope and tests.

Live service entries must stay read-only unless the project explicitly expands scope. Domain operations such as record creation, validation, query, computation, and registry refresh are intentionally excluded from the initial service connection layer.

Deployment artifact entries must stay grounded in the canonical `dp-system-gitops-template` repository. Generated artifacts are starter outputs for planning and review; they should not drift into a parallel deployment framework.

Reference-example entries must distinguish concrete demo details from reusable patterns. The assistant should generalize from examples, not imply that the example product, payload, auth mode, storage, or local stack is mandatory.

Update-channel entries must stay read-only and explicit. Stable architecture and scope guidance should remain in the local catalog; version-sensitive facts should come from update checks when current metadata is needed. Repository-discovery channels may propose new model update channels, but the server should not silently turn unknown repositories into generated deployment inputs. Model artifact channels should use `model_artifact_version`; model architecture documentation and model templates should use separate update roles.
