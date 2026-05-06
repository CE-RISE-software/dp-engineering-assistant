# Changelog

All notable changes to the CE-RISE Digital Passport Engineering Assistant project will be documented in this file.

## [0.0.1] - 2026-05-06

### Added
- Initial repo-native stdio MCP server setup.
- Deterministic local CE-RISE solution catalog.
- Initial MCP tools for solution discovery, component listing, goal mapping, architecture recommendation, implementation planning, and readiness assessment.
- Initial general Digital Passport adoption workflow tools for adoption context assessment, value-chain flow mapping, value-opportunity identification, adoption path recommendation, and roadmap generation.
- Initial connected-source manifest and tools for listing, checking, inspecting, and snapshotting CE-RISE source repositories and documentation references.
- Initial read-only live service connection manifest and tools for health, readiness, version, and OpenAPI discovery.
- Initial deployment artifact manifest and tools for planning, generating, and readiness-checking Compose/Kubernetes starter outputs derived from the CE-RISE GitOps template.
- Initial reference-example manifest and tools for generalizing reusable patterns from the local demonstrator without treating its concrete data or local-only settings as defaults.
- Initial update channel manifest and tools for optional current release, tag, documentation, and artifact metadata checks.
- Model repository discovery for the configured CE-RISE model namespace, returning candidate update channels for newly available data model repositories.
- Expanded explicit model update channels for currently discovered CE-RISE model repositories, with separate roles for model artifacts, model architecture documentation, and model templates.
- Update-aware deployment artifact generation can add checked model artifact channels to the generated registry catalog while excluding model documentation and template channels.
- Deployment artifact generation can include checked update metadata through `check_remote_updates`, returning `version_context` and `VERSION-CONTEXT.md`.
- Adoption, architecture, value-chain, and roadmap outputs now include connected CE-RISE source references and read-only live service connection candidates.
- Initial MCP resources for the solution catalog, connected-source manifest, live service connection manifest, deployment artifact manifest, reference-example manifest, update channel manifest, and assistant scope rule.
- Local run, smoke, validation, and unit-test scripts.
- Container smoke script and MCP Registry OCI ownership label.
- MCP registry metadata and GitHub mirror workflow for OCI image publication and MCP registry publication.
- Project-specific README, documentation, citation, and Zenodo metadata.
