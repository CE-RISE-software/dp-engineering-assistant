# Changelog

All notable changes to the CE-RISE Digital Passport Engineering Assistant project will be documented in this file.

## [0.0.2] - 2026-11-04

### Added
- SEE Impacts discovery, model references, release tracking, and read-only service probes.
- Compose and Kubernetes fragments for independently selected CE-RISE services.
- Static CE-RISE configuration review with field-specific findings.

### Changed
- Preserved mixed CE-RISE/external selections; reference architectures remain optional and external parts are outside assessment.
- Updated pinned images, documentation, examples, and automated tests.

## [0.0.1] - 2026-05-07

### Added
- First repo-native stdio MCP server for CE-RISE Digital Passport engineering assistance, exposing deterministic tools and resources for capability discovery, component selection, adoption context assessment, value-chain mapping, architecture guidance, implementation planning, and readiness checks.
- Curated CE-RISE knowledge manifests for solution components, connected repositories and documentation, read-only live service probes, reference-example generalization, update channels, and deployment artifact templates, with explicit non-substitution boundaries.
- Update-aware workflows for checking current software, model, example, deployment-template, and documentation metadata, including CE-RISE model repository discovery and checked model artifact versions in generated registry catalogs.
- Deployment artifact planning and generation for Docker Compose and Kubernetes starter outputs derived from the CE-RISE GitOps template, including `VERSION-CONTEXT.md` and readiness guidance for operator review.
- Release and publication assets for local validation, container smoke testing, Codeberg Pages documentation, GitHub mirror release automation, GHCR OCI image publication, MCP Registry metadata, and MCPO/OpenAPI reachability documentation.
