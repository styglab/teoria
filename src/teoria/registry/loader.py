from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from teoria.models import FormatRegistry, SourceRegistry
from teoria.registry.diagnostics import Diagnostic


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@dataclass(slots=True)
class RegistryCatalog:
    root: Path
    sources: dict[str, SourceRegistry]
    source_paths: dict[str, Path]
    formats: dict[str, Any]


class RegistryLoadError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(map(str, diagnostics)))


class RegistryLoader:
    def __init__(self, root: Path | str = "registries") -> None:
        self.root = Path(root)

    def load(self) -> RegistryCatalog:
        diagnostics: list[Diagnostic] = []
        sources: dict[str, SourceRegistry] = {}
        source_paths: dict[str, Path] = {}
        formats: dict[str, Any] = {}

        for path in sorted((self.root / "format").glob("*.yaml")):
            document = self._parse(path, diagnostics)
            if document is None:
                continue
            registry = self._validate(FormatRegistry, document, path, diagnostics)
            if registry:
                for definition in registry.formats:
                    if definition.id in formats:
                        diagnostics.append(Diagnostic("duplicate_format", f"duplicate format id '{definition.id}'", path))
                    formats[definition.id] = definition

        for path in sorted((self.root / "source").glob("*.yaml")):
            document = self._parse(path, diagnostics)
            if document is None:
                continue
            registry = self._validate(SourceRegistry, document, path, diagnostics)
            if registry:
                source_id = registry.source.id
                if source_id in sources:
                    diagnostics.append(Diagnostic("duplicate_source", f"duplicate source id '{source_id}'", path))
                sources[source_id] = registry
                source_paths[source_id] = path

        if diagnostics:
            raise RegistryLoadError(diagnostics)
        return RegistryCatalog(root=self.root, sources=sources, source_paths=source_paths, formats=formats)

    @staticmethod
    def _parse(path: Path, diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
        try:
            data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
            if not isinstance(data, dict):
                raise TypeError("registry document must be a mapping")
            return data
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
