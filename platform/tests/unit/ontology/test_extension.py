from pathlib import Path

from teoria.ontology.extension import OntologyExtensionManifest


ROOT = Path(__file__).parents[3]


def test_enterprise_context_extension_is_source_independent() -> None:
    manifest = OntologyExtensionManifest.load(
        ROOT / "ontology_migrations" / "teoria_enterprise_context_v1.yaml"
    )
    codes = {item.code for item in manifest.objects}
    assert {"Qualification", "Certification", "TaxpayerStatusObservation",
            "FinancialStatement", "FinancialFact", "BusinessEntityRelationship"} <= codes
    assert not any(code.startswith(("MSS", "NTS", "FSC")) for code in codes)
