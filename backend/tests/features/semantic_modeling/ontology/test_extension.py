from pathlib import Path

from teoria.features.semantic_modeling.ontology.extension import OntologyExtensionManifest


ROOT = (Path(__file__).resolve().parents[5] / 'backend')


def test_enterprise_context_extension_is_source_independent() -> None:
    manifest = OntologyExtensionManifest.load(
        ROOT / "authoring" / "ontology_migrations" / "applied" / "2026_10_initial_unification" / "teoria_enterprise_context_v1.yaml"
    )
    codes = {item.code for item in manifest.objects}
    assert {"Qualification", "Certification", "TaxpayerStatusObservation",
            "FinancialStatement", "FinancialFact", "BusinessEntityRelationship"} <= codes
    assert not any(code.startswith(("MSS", "NTS", "FSC")) for code in codes)
