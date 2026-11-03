# Deployment Artifacts

The server can return starter deployment files through `generate_deployment_artifacts`.

These outputs are derived from the existing CE-RISE Digital Passport System GitOps Template:

- Docker Compose baseline with `hex-core-service`;
- optional Compose profiles for the internal adapter, RE Indicators, and SEE Impacts;
- Kubernetes base aligned with the existing template's overlay workflow;
- development and production overlays;
- optional Kubernetes extensions for RE Indicators and SEE Impacts, with individual and combined overlays.

The generated files are returned as structured MCP content:

- `path`: relative file path, such as `compose/docker-compose.yml`;
- `mime_type`: content type hint;
- `description`: short file purpose;
- `content`: complete file content.

`generate_deployment_artifact_plan` and `generate_deployment_artifacts` accept `check_remote_updates`. When this is true, the same generation call checks configured update channels and returns a `version_context`. Generated artifact sets also include `VERSION-CONTEXT.md`. Checked `model_artifact_version` tags are used where they map cleanly to generated registry catalog entries. Model architecture documentation and model template channels remain visible in version context but are not emitted as registry catalog model entries.

The server does not write these files to disk and does not deploy anything.

Both deployment tools accept `include_see_impacts`, independently of `include_re_indicators`.
If omitted, each option follows the corresponding service in `selected_components`. An explicit
`false` excludes that service. SEE generation includes:

- the `see-impacts` Compose profile, exposing the service on `127.0.0.1:8084` by default;
- Product System `0.0.1`, LCI Dataset `0.0.1`, and Integrated LCA `0.2.0` registry entries;
- HEX Core connection and bearer-token settings, request/calculation timeouts, and concurrency;
- a writable Brightway workspace, service probes, and a cluster-local Kubernetes Service;
- `dev-see-impacts` and `prod-see-impacts` overlays;
- `dev-calculations` and `prod-calculations` overlays when RE Indicators is also selected.

Service image defaults match the GitOps template: HEX Core `v0.0.9`, JSONDB storage `v0.0.1`,
RE Indicators `v0.0.1`, and SEE Impacts `v0.0.1`. Remote release checks report current metadata;
they do not automatically replace these image pins. Checked model artifact tags can update the
generated registry entries.

When HEX Core requires authentication, configure `SEE_IMPACTS_HEX_CORE_BEARER_TOKEN` for Compose,
or supply a `see-impacts-auth` Secret containing `HEX_CORE_BEARER_TOKEN` in the Kubernetes namespace.
The Secret is operator-managed and is not generated with credentials.

## Recommended Flow

1. Use `generate_deployment_artifact_plan` to map the adoption context and selected CE-RISE services to artifact profiles.
2. Use `assess_deployment_artifact_readiness` to check whether runtime, service, adapter, registry, auth, overlay, and operational-check decisions are declared.
3. Use `generate_deployment_artifacts` to return starter files.
4. Validate and adapt those files against the canonical `dp-system-gitops-template` repository.

The scenarios in `examples/02-deployment-artifacts` show RE Indicators and SEE Impacts selections
for Compose and Kubernetes, including the combined calculation overlays.

## Boundary

Deployment artifacts are planning and handover outputs. They help a user make the most of the existing CE-RISE deployment template, but they do not replace that template, its validation scripts, or the deployment documentation of the underlying services.
