# Update-Aware Generation Example

This example shows the normal generation path with current upstream metadata enabled.

The important point is that users do not need to run a separate update workflow before generating artifacts. The generation tool can check configured update channels and carry the result into the generated artifact set.

The same update layer covers software components, reference examples, deployment templates, and known model repositories. If the question is whether additional CE-RISE model repositories have appeared under the model namespace, call `discover_model_repositories` first and review the returned candidate channels.

Example request:

```json
{
  "target": "both",
  "project_name": "digital passport pilot",
  "selected_components": ["hex_core_service", "re_indicators_calculation_service"],
  "include_re_indicators": true,
  "external_io_adapter_url": "https://io-adapter.example.org",
  "check_remote_updates": true,
  "timeout_seconds": 10
}
```

Expected response shape:

```json
{
  "result_type": "deployment_artifact_generation_result",
  "content": {
    "version_context": {
      "policy": "current_metadata_when_checked",
      "remote_checked": true,
      "resolved_versions": [
        {
          "channel_id": "dp_record_metadata_tags",
          "component_id": "ce_rise_models",
          "version": "pages-v..."
        }
      ]
    },
    "files": [
      {
        "path": "compose/registry/catalog.json"
      },
      {
        "path": "k8s/base/registry-configmap.yaml"
      },
      {
        "path": "VERSION-CONTEXT.md"
      }
    ]
  }
}
```

Behavior:

- if configured update channels are reachable, checked `model_artifact_version` tags are used where they map cleanly to generated registry catalog entries;
- generated artifacts include `VERSION-CONTEXT.md`;
- if a channel is unreachable or cannot be parsed, stable manifest defaults are preserved and the version context records the issue;
- deployment, secrets, service auth, and operational acceptance still remain adopter/operator decisions.
