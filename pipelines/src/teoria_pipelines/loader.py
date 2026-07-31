from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from teoria_pipelines.diagnostics import Diagnostic
from teoria_pipelines.schema import ConnectorRegistry, PipelineDefinition, PipelineRegistry, ProviderReference


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError("while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@dataclass(slots=True)
class PipelineCatalog:
    root: Path
    connectors: dict[str, ConnectorRegistry]
    connector_paths: dict[str, Path]
    pipelines: dict[str, PipelineDefinition]
    pipeline_paths: dict[str, Path]
    references: dict[str, ProviderReference] = field(default_factory=dict)
    reference_paths: dict[str, Path] = field(default_factory=dict)


class PipelineLoadError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(map(str, diagnostics)))


class PipelineLoader:
    """Load Data Pipeline-owned Connector and Pipeline contracts."""

    def __init__(self, root: Path | str = "pipelines") -> None:
        self.root = Path(root)

    def load(self) -> PipelineCatalog:
        diagnostics: list[Diagnostic] = []
        if not self.root.is_dir():
            raise PipelineLoadError(
                [Diagnostic("pipeline_root_not_found", "pipeline project directory does not exist", self.root)]
            )

        connectors: dict[str, ConnectorRegistry] = {}
        connector_paths: dict[str, Path] = {}
        pipelines: dict[str, PipelineDefinition] = {}
        pipeline_paths: dict[str, Path] = {}
        references: dict[str, ProviderReference] = {}
        reference_paths: dict[str, Path] = {}

        for path in sorted((self.root / "connectors").glob("*.yaml")):
            document = self._parse(path, diagnostics)
            registry = self._validate(ConnectorRegistry, document, path, diagnostics) if document else None
            if registry:
                connector_id = registry.connector.id
                if connector_id in connectors:
                    diagnostics.append(Diagnostic("duplicate_connector", f"duplicate connector id '{connector_id}'", path))
                connectors[connector_id] = registry
                connector_paths[connector_id] = path

        for path in sorted((self.root / "definitions").rglob("*.yaml")):
            document = self._parse(path, diagnostics)
            registry = self._validate(PipelineRegistry, document, path, diagnostics) if document else None
            if registry:
                pipeline_id = registry.pipeline.id
                if pipeline_id in pipelines:
                    diagnostics.append(Diagnostic("duplicate_pipeline", f"duplicate pipeline id '{pipeline_id}'", path))
                pipelines[pipeline_id] = registry.pipeline
                pipeline_paths[pipeline_id] = path

        reference_root = self.root / "references" / "providers"
        for path in sorted(reference_root.glob("*/*/metadata.yaml")):
            document = self._parse(path, diagnostics)
            reference = self._validate(ProviderReference, document, path, diagnostics) if document else None
            if reference:
                if reference.source in references:
                    diagnostics.append(
                        Diagnostic("duplicate_reference", f"duplicate provider reference for connector '{reference.source}'", path)
                    )
                references[reference.source] = reference
                reference_paths[reference.source] = path

        if not connectors and not pipelines:
            diagnostics.append(
                Diagnostic("empty_pipeline_project", "pipeline project contains no Connector or Pipeline definitions", self.root)
            )
        if diagnostics:
            raise PipelineLoadError(diagnostics)
        return PipelineCatalog(
            root=self.root,
            connectors=connectors,
            connector_paths=connector_paths,
            pipelines=pipelines,
            pipeline_paths=pipeline_paths,
            references=references,
            reference_paths=reference_paths,
        )

    @staticmethod
    def _parse(path: Path, diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
        try:
            value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
            if not isinstance(value, dict):
                raise TypeError("pipeline document must be a mapping")
            return value
        except (OSError, yaml.YAMLError, TypeError) as exc:
            diagnostics.append(Diagnostic("invalid_yaml", str(exc), path))
            return None

    @staticmethod
    def _validate(model: type[Any], data: dict[str, Any], path: Path, diagnostics: list[Diagnostic]) -> Any | None:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            for error in exc.errors(include_url=False):
                diagnostics.append(
                    Diagnostic(
                        "invalid_schema",
                        error["msg"],
                        path,
                        location=".".join(map(str, error["loc"])),
                    )
                )
            return None
