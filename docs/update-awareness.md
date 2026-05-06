# Update Awareness

The server separates stable guidance from version-sensitive facts.

Stable guidance lives in the local catalog:

- scope rules;
- non-substitution boundaries;
- component roles;
- architecture and adoption patterns;
- reference-example generalization;
- deployment artifact shape.

Version-sensitive facts live in configured update channels:

- repository releases;
- repository tags;
- repository discovery;
- documentation availability;
- generated artifact availability.

Use `list_update_channels` to inspect the configured channels, then `check_update_channels` when current metadata is needed. Use `build_update_aware_solution_context` when a workflow should combine stable component guidance with optional current upstream metadata.

Generation tools can also carry this context directly. For deployment artifact generation, pass `check_remote_updates: true` to `generate_deployment_artifact_plan` or `generate_deployment_artifacts`. The result includes `version_context`, and generated artifact sets include `VERSION-CONTEXT.md`. Where a checked `model_artifact_version` tag maps cleanly to registry catalog fields, the generated registry catalog uses the checked version. Model template and architecture/documentation channels are included in version context but excluded from registry catalog entries.

See `examples/03-update-aware-generation` for a request and expected response shape.

Use `discover_model_repositories` when the current question is whether the CE-RISE model namespace contains additional model repositories that are not yet explicitly tracked. The tool checks the configured CE-RISE model repository root and returns candidate `gitea_tags` update channels for new repositories. Those candidates are review inputs; generated artifacts should use a newly discovered model only after it has an explicit model-artifact update channel. Template and architecture/documentation repositories can still be tracked for version awareness, but they are not treated as data model artifact inputs.

Normal workflow tools also include an `update_awareness` field whenever they select or expose CE-RISE services, models, examples, deployment templates, or source references. That field is deliberately non-blocking:

- it says whether current metadata was checked;
- it lists the configured update channels relevant to the selected components;
- it recommends `build_update_aware_solution_context` or `check_update_channels` before implementation, deployment, or detailed technical decisions.

Remote checks are explicit. The server does not silently call upstream repositories from every planning tool, because deterministic behavior and offline use are still important.

This means the MCP server does not need a new release just because a CE-RISE model, service, example, or deployment template publishes a new version. A new MCP release is needed only when the stable guidance, tool behavior, manifests, generated artifact logic, or supported update channels themselves change.
