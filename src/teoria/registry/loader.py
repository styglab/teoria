from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from teoria.registry.schema import (
    CapabilityDefinition,
    CapabilityRegistry,
    DataTypeDefinition,
    DataTypeRegistry,
    MappingDefinition,
    MappingRegistry,
    OntologyDefinition,
    OntologyRegistry,
    ProviderReference,
    SourceRegistry,
    ValueSetDefinition,
    ValueSetRegistry,
)
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
    data_types: dict[str, DataTypeDefinition]
    value_sets: dict[str, ValueSetDefinition] = field(default_factory=dict)
    ontologies: dict[str, OntologyDefinition] = field(default_factory=dict)
    ontology_paths: dict[str, Path] = field(default_factory=dict)
    mappings: dict[str, MappingDefinition] = field(default_factory=dict)
    mapping_paths: dict[str, Path] = field(default_factory=dict)
    capabilities: dict[str, CapabilityDefinition] = field(default_factory=dict)
    capability_paths: dict[str, Path] = field(default_factory=dict)
    references: dict[str, ProviderReference] = field(default_factory=dict)
    reference_paths: dict[str, Path] = field(default_factory=dict)


class RegistryLoadError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(map(str, diagnostics)))


class RegistryLoader:
    def __init__(
        self,
        root: Path | str = "registries",
        reference_root: Path | str | None = None,
    ) -> None:
        self.root = Path(root)
        self.reference_root = Path(reference_root) if reference_root is not None else self.root.parent / "references" / "providers"

    def load(self) -> RegistryCatalog:
        diagnostics: list[Diagnostic] = []
        if not self.root.is_dir():
            raise RegistryLoadError(
                [Diagnostic("registry_root_not_found", "registry root directory does not exist", self.root)]
            )
        sources: dict[str, SourceRegistry] = {}
        source_paths: dict[str, Path] = {}
        data_types: dict[str, DataTypeDefinition] = {}
        value_sets: dict[str, ValueSetDefinition] = {}
        ontologies: dict[str, OntologyDefinition] = {}
        ontology_paths: dict[str, Path] = {}
        mappings: dict[str, MappingDefinition] = {}
        mapping_paths: dict[str, Path] = {}
        capabilities: dict[str, CapabilityDefinition] = {}
        capability_paths: dict[str, Path] = {}
        references: dict[str, ProviderReference] = {}
        reference_paths: dict[str, Path] = {}

        data_type_paths = [self.root / "core" / "data_types.yaml"]
        for path in data_type_paths:
            if not path.exists():
                continue
            document = self._parse(path, diagnostics)
            if document is None:
                continue
            registry = self._validate(DataTypeRegistry, document, path, diagnostics)
            if registry:
                for definition in registry.data_types:
                    if definition.id in data_types:
                        diagnostics.append(Diagnostic("duplicate_data_type", f"duplicate data type id '{definition.id}'", path))
                    data_types[definition.id] = definition

        value_set_path = self.root / "core" / "value_sets.yaml"
        if value_set_path.exists():
            document = self._parse(value_set_path, diagnostics)
            if document is not None:
                registry = self._validate(ValueSetRegistry, document, value_set_path, diagnostics)
                if registry:
                    for definition in registry.value_sets:
                        if definition.id in value_sets:
                            diagnostics.append(Diagnostic("duplicate_value_set", f"duplicate value set id '{definition.id}'", value_set_path))
                        value_sets[definition.id] = definition

        ontology_paths_to_load = list((self.root / "ontologies").glob("*.yaml"))
        ontology_paths_to_load.extend((self.root / "domains").glob("*/ontology.yaml"))
        for path in sorted(ontology_paths_to_load):
            document = self._parse(path, diagnostics)
            if document is None:
                continue
            registry = self._validate(OntologyRegistry, document, path, diagnostics)
            if registry:
                ontology_id = registry.ontology.id
                if ontology_id in ontologies:
                    diagnostics.append(Diagnostic("duplicate_ontology", f"duplicate ontology id '{ontology_id}'", path))
                ontologies[ontology_id] = registry.ontology
                ontology_paths[ontology_id] = path

        for path in sorted((self.root / "sources").glob("*.yaml")):
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

        mapping_paths_to_load = list((self.root / "mappings").glob("*.yaml"))
        mapping_paths_to_load.extend((self.root / "domains").glob("*/mappings/*.yaml"))
        for path in sorted(mapping_paths_to_load):
            document = self._parse(path, diagnostics)
            if document is None:
                continue
            registry = self._validate(MappingRegistry, document, path, diagnostics)
            if registry:
                mapping_id = registry.mapping.id
                if mapping_id in mappings:
                    diagnostics.append(Diagnostic("duplicate_mapping", f"duplicate mapping id '{mapping_id}'", path))
                mappings[mapping_id] = registry.mapping
                mapping_paths[mapping_id] = path

        capability_paths_to_load = list((self.root / "capabilities").glob("*.yaml"))
        capability_paths_to_load.extend((self.root / "domains").glob("*/capabilities/*.yaml"))
        for path in sorted(capability_paths_to_load):
            document = self._parse(path, diagnostics)
            if document is None:
                continue
            registry = self._validate(CapabilityRegistry, document, path, diagnostics)
            if registry:
                capability_id = registry.capability.id
                if capability_id in capabilities:
                    diagnostics.append(Diagnostic("duplicate_capability", f"duplicate capability id '{capability_id}'", path))
                capabilities[capability_id] = registry.capability
                capability_paths[capability_id] = path

        if self.reference_root.is_dir():
            for path in sorted(self.reference_root.glob("*/*/metadata.yaml")):
                document = self._parse(path, diagnostics)
                if document is None:
                    continue
                reference = self._validate(ProviderReference, document, path, diagnostics)
                if reference:
                    if reference.source in references:
                        diagnostics.append(Diagnostic("duplicate_reference", f"duplicate provider reference for source '{reference.source}'", path))
                    references[reference.source] = reference
                    reference_paths[reference.source] = path

        if not any((sources, data_types, value_sets, ontologies, mappings, capabilities)):
            diagnostics.append(Diagnostic("empty_registry", "registry root contains no recognized registry documents", self.root))
        if diagnostics:
            raise RegistryLoadError(diagnostics)
        return RegistryCatalog(
            root=self.root,
            sources=sources,
            source_paths=source_paths,
            data_types=data_types,
            value_sets=value_sets,
            ontologies=ontologies,
            ontology_paths=ontology_paths,
            mappings=mappings,
            mapping_paths=mapping_paths,
            capabilities=capabilities,
            capability_paths=capability_paths,
            references=references,
            reference_paths=reference_paths,
        )

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
