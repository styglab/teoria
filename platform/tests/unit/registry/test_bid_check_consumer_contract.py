from pathlib import Path

import yaml

from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]
CONTRACT = ROOT.parent / "docs" / "integration" / "bid_check_capabilities.yaml"


def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_bid_check_consumer_contract_has_unique_capabilities_and_explicit_status() -> None:
    contract = _load_contract()
    capabilities = contract["capabilities"]
    identifiers = [item["id"] for item in capabilities]

    assert contract["consumer"] == "bid_check"
    assert contract["ontology_decision"] == {
        "change_required": True,
        "strategy": "new_draft_from_published",
        "target_namespace": "teoria",
        "reuse_stable_concepts": True,
        "rationale": contract["ontology_decision"]["rationale"],
    }
    assert len(identifiers) == 30
    assert len(set(identifiers)) == len(identifiers)
    assert {item["status"] for item in capabilities} == {"active", "migration_required"}


def test_bid_check_active_capabilities_are_discoverable_and_migrations_are_explicit() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    contract = _load_contract()
    active = {
        item["id"] for item in contract["capabilities"] if item["status"] == "active"
    }
    migrations = {
        item["id"]: item["replacements"]
        for item in contract["capabilities"]
        if item["status"] == "migration_required"
    }

    assert len(active) == 27
    assert active <= set(catalog.capabilities)
    assert all(catalog.capabilities[item].lifecycle.status == "active" for item in active)
    assert set(migrations) == {
        "find_similar_bid_notices",
        "find_bid_relevant_companies",
        "analyze_bid_organization_field_companies",
    }
    assert set(migrations).isdisjoint(catalog.capabilities)
    assert all(set(replacements) <= set(catalog.capabilities) for replacements in migrations.values())

