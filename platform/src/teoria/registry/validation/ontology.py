from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog
from teoria.registry.validation.duplicates import check_duplicates

ONTOLOGY_BUILTIN_DATA_TYPES = {"string", "integer", "number", "boolean", "date", "datetime"}


def validate_value_sets(catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
    path = catalog.root / "core" / "value_sets.yaml"
    for value_set in catalog.value_sets.values():
        check_duplicates(
            [value.id for value in value_set.values],
            "value_set_value",
            path,
            diagnostics,
            f"value_sets.{value_set.id}.values",
        )


def validate_ontologies(catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
    for ontology_id, ontology in catalog.ontologies.items():
        path = catalog.ontology_paths[ontology_id]
        domain_ontology = path.name == "ontology.yaml" and path.parent.name == ontology.id
        if path.stem != ontology.id and not domain_ontology:
            diagnostics.append(Diagnostic("ontology_filename_mismatch", f"filename must match ontology id '{ontology.id}.yaml'", path, location="ontology.id"))

        object_types = {item.id: item for item in ontology.object_types}
        check_duplicates([item.id for item in ontology.object_types], "object_type", path, diagnostics, "ontology.object_types")
        check_duplicates([item.id for item in ontology.link_types], "link_type", path, diagnostics, "ontology.link_types")

        for obj in ontology.object_types:
            location = f"ontology.object_types.{obj.id}"
            properties = {prop.id: prop for prop in obj.properties}
            check_duplicates([prop.id for prop in obj.properties], "ontology_property", path, diagnostics, f"{location}.properties")
            if obj.primary_key not in properties:
                diagnostics.append(Diagnostic("unknown_primary_key", f"unknown property '{obj.primary_key}'", path, location=f"{location}.primary_key"))
            for prop in obj.properties:
                prop_location = f"{location}.properties.{prop.id}"
                if prop.data_type and prop.data_type not in ONTOLOGY_BUILTIN_DATA_TYPES and prop.data_type not in catalog.data_types:
                    diagnostics.append(Diagnostic("unknown_data_type", f"unknown data type '{prop.data_type}'", path, location=prop_location))
                if prop.value_set and prop.value_set not in catalog.value_sets:
                    diagnostics.append(Diagnostic("unknown_value_set", f"unknown value set '{prop.value_set}'", path, location=prop_location))
            for example_index, example in enumerate(obj.examples):
                for property_id in example:
                    if property_id not in properties:
                        diagnostics.append(Diagnostic("unknown_example_property", f"unknown example property '{property_id}'", path, location=f"{location}.examples.{example_index}"))
        for link in ontology.link_types:
            location = f"ontology.link_types.{link.id}"
            for side_name, object_type in (("source", link.source), ("target", link.target)):
                if "." in object_type:
                    referenced_ontology_id, referenced_object_id = object_type.split(".", 1)
                    referenced_ontology = catalog.ontologies.get(referenced_ontology_id)
                    exists = bool(referenced_ontology and referenced_object_id in {item.id for item in referenced_ontology.object_types})
                else:
                    exists = object_type in object_types
                if not exists:
                    diagnostics.append(Diagnostic("unknown_link_object_type", f"unknown object type '{object_type}'", path, location=f"{location}.{side_name}"))
