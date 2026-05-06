# Deployment Artifacts

The server can return starter deployment files through `generate_deployment_artifacts`.

These outputs are derived from the existing CE-RISE Digital Passport System GitOps Template:

- Docker Compose baseline with `hex-core-service`;
- optional Compose profiles for `internal-adapter` and `re-indicators-calculation-service`;
- Kubernetes base aligned with the existing template's overlay workflow;
- development and production overlays;
- optional Kubernetes extension for RE indicators.

The generated files are returned as structured MCP content:

- `path`: relative file path, such as `compose/docker-compose.yml`;
- `mime_type`: content type hint;
- `description`: short file purpose;
- `content`: complete file content.

`generate_deployment_artifact_plan` and `generate_deployment_artifacts` accept `check_remote_updates`. When this is true, the same generation call checks configured update channels and returns a `version_context`. Generated artifact sets also include `VERSION-CONTEXT.md`. Checked model tags are used where they map cleanly to generated registry catalog entries.

The server does not write these files to disk and does not deploy anything.

## Recommended Flow

1. Use `generate_deployment_artifact_plan` to map the adoption context and selected CE-RISE services to artifact profiles.
2. Use `assess_deployment_artifact_readiness` to check whether runtime, service, adapter, registry, auth, overlay, and operational-check decisions are declared.
3. Use `generate_deployment_artifacts` to return starter files.
4. Validate and adapt those files against the canonical `dp-system-gitops-template` repository.

The concrete Digital Passport scenario in `examples/02-deployment-artifacts` shows the expected profile selection and file list for a Compose plus Kubernetes output set with the RE indicators extension enabled.

## Boundary

Deployment artifacts are planning and handover outputs. They help a user make the most of the existing CE-RISE deployment template, but they do not replace that template, its validation scripts, or the deployment documentation of the underlying services.
