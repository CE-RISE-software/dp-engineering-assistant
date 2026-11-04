# Deployment Artifacts

The server can return starter deployment files through `generate_deployment_artifacts`.

These outputs are derived from the existing CE-RISE Digital Passport System GitOps Template:

- optional Docker Compose reference baseline with `hex-core-service`;
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
- Product System `0.0.1`, LCI Dataset `0.0.1`, and Integrated LCA `0.2.0` registry entries when HEX Core is selected;
- HEX Core connection and bearer-token settings, request/calculation timeouts, and concurrency;
- a writable Brightway workspace, service probes, and a cluster-local Kubernetes Service;
- `dev-see-impacts` and `prod-see-impacts` overlays when HEX Core is selected;
- `dev-calculations` and `prod-calculations` overlays when HEX Core and RE Indicators are also selected.

An explicit `selected_components` list is the user's composition, not a request to complete a
CE-RISE stack. Selecting only SEE produces its Compose profile and Kubernetes extension without
a local HEX Core, model registry, or namespace/overlay structure. Configure `hex_core_base_url`
with the chosen validation endpoint; an external implementation must satisfy the interface used
by the selected CE-RISE service, but this tool does not verify that implementation.

External or unsupported component labels remain in `declared_components` and
`outside_generation_scope`. They are not generated or treated as missing. An external-only
selection returns `generation_status: not_applicable` and no files. Without `selected_components`,
the generator offers the optional HEX Core GitOps reference baseline. Standalone Kubernetes
extensions can be incorporated into the adopter's own overlays and namespace workflow.

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
4. Review the selected CE-RISE fragments against their component documentation and integrate them into the adopter's chosen deployment workflow; the GitOps template is an optional reference.

The scenarios in `examples/02-deployment-artifacts` show RE Indicators and SEE Impacts selections
for Compose and Kubernetes, including the combined calculation overlays.

## Configuration Consistency Review

`review_configuration_consistency` reviews the supplied configuration contents. Unlike the
readiness checklist, it checks relationships between the actual settings:

- CE-RISE container ports and listening ports, including conflicting bindings that affect a CE-RISE service; external-only conflicts are outside scope;
- calculation-service URLs and the supplied HEX Core service or Kubernetes Service ports;
- model registrations for explicitly connected CE-RISE calculator/HEX Core pairs:
  `re-indicators-specification` for RE Indicators, and `product-system`, `lci-dataset`, and
  `integrated-lca` for SEE; no such catalog requirement is inferred for an external endpoint;
- duplicate model/version entries, missing artifact URLs, allowed hosts, HTTPS policy, and
  mismatches between catalog identities and versioned CE-RISE artifact URLs;
- HEX Core authentication settings, explicit local no-auth permission, production no-auth
  configuration, and the SEE-to-HEX Core token setting;
- Kubernetes Service targets, named ports, probes, and supplied ConfigMap/Secret references.

Pass the inputs as an MCP tool call:

| Argument | Content |
| --- | --- |
| `target` | `compose` or `kubernetes` |
| `files` | Array of objects with `path` and JSON/YAML `content`; paths identify findings and are not opened |
| `environment` | `local` (default), `dev`, or `prod` |
| `model_catalog` | Optional catalog object or array when the referenced catalog contents are not included in `files` |

Supply the output of `docker compose config` or `kubectl kustomize`, rather than unevaluated
variables or overlay sources. For example, render the selected configuration in your deployment
workspace:

```bash
docker compose -f "$PWD/compose/docker-compose.yml" --env-file "$PWD/compose/.env" --profile see-impacts config > /tmp/ce-rise-compose.yaml
kubectl kustomize k8s/overlays/dev-see-impacts > /tmp/ce-rise-kubernetes.yaml
```

The MCP client passes the chosen rendered file's contents in `files`, along with any referenced
catalog file. A mounted or inline catalog takes precedence over `model_catalog`. Review one
Kubernetes environment at a time. The tool supports at most 100 supplied files and 2 MB of contents.

Rendered configuration can contain credentials. Replace real secret values with non-empty
redacted values while preserving their keys and references. For Kubernetes, `Secret.stringData`
can carry those redacted values. The report does not echo environment or credential values.

The result contains `findings` with a code, severity, field path, explanation, and recommended
correction, plus `unchecked` items for missing context. For example, a calculation container
configured with `HEX_CORE_BASE_URL=http://localhost:8080` while HEX Core runs in a different
container produces a `container_localhost_core` finding and recommends using the service address.

`consistent` means no inconsistency was found in the supported CE-RISE static checks; it is not
a judgment on the complete mixed system. `inconsistent` means a CE-RISE configuration error was
found. `incomplete` means some supplied CE-RISE settings could not be checked because their catalog
contents, variable values, or referenced configuration were not supplied. `not_applicable` means
no supported CE-RISE component was supplied.

External components and validation endpoints are reported in `out_of_scope`, not in `unchecked`.
They do not make a CE-RISE review incomplete or imply that another CE-RISE component must be
added. For example, SEE configured with a valid external validation URL can be reviewed without
including a HEX Core deployment or model catalog. Conversely, if SEE explicitly points to a
supplied HEX Core instance, the checker can compare that declared connection's model registrations.
HEX Core catalogs can contain external models, subject to HEX Core's configured artifact policies.

The tool does not fetch artifacts, validate records,
verify credentials, execute deployment commands, or establish operational readiness.

## Boundary

Deployment artifacts are optional CE-RISE configuration fragments, not a required complete
architecture. They support independent reuse and mixed systems without replacing or assessing
the adopter's external components, models, or deployment workflow.
