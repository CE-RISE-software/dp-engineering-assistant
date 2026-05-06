# Deployment Artifact Output Example

This example exercises the deployment-artifact output path for the main CE-RISE Digital Passport adoption use case.

Scenario:

- an organization is preparing a Digital Passport pilot for a product, material, or asset family;
- HEX Core Service is the system integration point;
- the workflow may need RE Indicators Calculation Service for circularity and resource-efficiency value;
- deployment planning should follow the existing CE-RISE GitOps template shape.

Use the tools in this order:

1. `generate_deployment_artifact_plan`
2. `assess_deployment_artifact_readiness`
3. `generate_deployment_artifacts`

Example artifact plan request:

```json
{
  "target": "both",
  "selected_components": ["hex_core_service", "re_indicators_calculation_service"],
  "include_re_indicators": true,
  "adoption_context": {
    "organization_role": "manufacturer",
    "passport_scope": "product family",
    "compliance_drivers": ["customer reporting request", "regulatory reporting preparation"],
    "value_chain_actors": ["supplier", "manufacturer", "customer", "repair partner", "recycler"],
    "shared_information": ["product identity", "material composition", "traceability evidence", "repair and end-of-life information"],
    "value_goals": ["reduce repeated reporting", "support circularity services"]
  }
}
```

Expected artifact profiles:

- `compose_baseline_external_adapter`
- `compose_re_indicators_profile`
- `kubernetes_base`
- `kubernetes_dev_overlay`
- `kubernetes_prod_overlay`
- `kubernetes_re_indicators_extension`

Example readiness request:

```json
{
  "deployment_context": {
    "target_runtime": "both",
    "selected_services": ["hex_core_service", "re_indicators_calculation_service"],
    "io_adapter_strategy": "external HTTP adapter for first deployment review",
    "model_registry_strategy": "local pinned catalog with CE-RISE model artifact URLs",
    "auth_strategy": "JWT/JWKS for production, insecure auth only in dev overlay",
    "environment_overlays": ["compose", "k8s dev", "k8s prod", "re-indicators extension overlays"],
    "operational_checks": ["health", "readiness", "OpenAPI", "registry catalog render"]
  }
}
```

Example artifact generation request:

```json
{
  "target": "both",
  "project_name": "digital passport pilot",
  "selected_components": ["hex_core_service", "re_indicators_calculation_service"],
  "include_re_indicators": true,
  "external_io_adapter_url": "https://io-adapter.example.org",
  "check_remote_updates": true
}
```

Expected generated file paths include:

- `compose/docker-compose.yml`
- `compose/.env.example`
- `compose/registry/catalog.json`
- `k8s/base/kustomization.yaml`
- `k8s/overlays/dev/kustomization.yaml`
- `k8s/overlays/prod/kustomization.yaml`
- `k8s/extensions/re-indicators/kustomization.yaml`
- `k8s/overlays/dev-re-indicators/kustomization.yaml`
- `k8s/overlays/prod-re-indicators/kustomization.yaml`
- `VERSION-CONTEXT.md`

When `check_remote_updates` is true, the result includes `version_context`, and generated registry catalog entries use checked model tags where the update channel maps cleanly to CE-RISE model artifact URLs.

The result also returns validation commands, including:

```bash
docker compose -f compose/docker-compose.yml --env-file compose/.env.example --profile re-indicators config
kubectl kustomize k8s/overlays/dev
kubectl kustomize k8s/overlays/prod
kubectl kustomize k8s/overlays/dev-re-indicators
kubectl kustomize k8s/overlays/prod-re-indicators
```

These outputs are starter artifacts for planning and review. They should be reconciled with the canonical `dp-system-gitops-template` repository before deployment.
