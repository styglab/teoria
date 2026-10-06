from pathlib import Path

from teoria.ontology.rule_manifest import BusinessRuleManifest


ROOT = Path(__file__).parents[3]


def test_business_rule_manifest_covers_identity_amount_and_attribution() -> None:
    manifest = BusinessRuleManifest.load(
        ROOT / "ontology_migrations" / "teoria_business_rules_v1.yaml"
    )
    assert {item.code for item in manifest.rules} == {
        "BID_NOTICE_IDENTITY", "PROCUREMENT_LOT_IDENTITY",
        "BID_PARTICIPATION_IDENTITY", "CONTRACT_EVENT_IDENTITY",
        "CURRENT_CONTRACT_VERSION", "CURRENT_CONTRACT_AMOUNT",
        "CONTRACT_PARTY_ATTRIBUTED_AMOUNT",
    }
