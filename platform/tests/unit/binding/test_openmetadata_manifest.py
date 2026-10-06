from pathlib import Path

from teoria.binding.openmetadata_manifest import OpenMetadataBindingManifest


ROOT = Path(__file__).parents[3]


def test_openmetadata_binding_plan_covers_physical_and_term_references() -> None:
    manifest = OpenMetadataBindingManifest.load(
        ROOT / "ontology_migrations" / "teoria_openmetadata_bindings_v1.yaml"
    )

    assert manifest.ontology_namespace == "teoria"
    assert len(manifest.bindings) == 11
    assert {item.entity_type for item in manifest.bindings} == {"column", "glossaryTerm"}
    assert len({item.ontology_stable_key for item in manifest.bindings}) == 10
    current_amount = [
        item for item in manifest.bindings
        if item.ontology_stable_key == "procurement.Contract.currentAmount"
    ]
    assert {item.target_type for item in current_amount} == {"data_asset", "glossary_term"}
