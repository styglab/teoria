from __future__ import annotations

from typing import Any

from teoria_provider.validator import ProviderContractValidator
from teoria_pipelines.diagnostics import Diagnostic
from teoria_pipelines.loader import PipelineCatalog


class PlatformIntegrationValidator:
    """Validate only the versioned boundary between Pipelines and Platform."""

    def validate(self, catalog: PipelineCatalog, platform_catalog: Any) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for connector_id, registry in catalog.connectors.items():
            diagnostics.extend(ProviderContractValidator().validate(
                registry.connector,
                data_types=platform_catalog.data_types,
                path=catalog.connector_paths[connector_id],
                root="connector",
            ))
        for pipeline_id, pipeline in catalog.pipelines.items():
            path = catalog.pipeline_paths[pipeline_id]
            sink = platform_catalog.sources.get(pipeline.sink.source)
            if sink is None or sink.source.type != "database":
                diagnostics.append(Diagnostic("invalid_pipeline_sink",
                    f"pipeline sink '{pipeline.sink.source}' must be a Semantic Platform database source",
                    path, location="pipeline.sink.source"))
                continue
            relation_ids = {item.id for item in sink.source.relations}
            for index, relation_id in enumerate(pipeline.sink.relations):
                if relation_id not in relation_ids:
                    diagnostics.append(Diagnostic("unknown_pipeline_sink_relation",
                        f"unknown sink relation '{relation_id}'", path,
                        location=f"pipeline.sink.relations.{index}"))
        return diagnostics
