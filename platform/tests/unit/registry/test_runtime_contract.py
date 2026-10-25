from copy import deepcopy
from pathlib import Path

from teoria.registry.loader import RegistryLoader
from teoria.registry.validation.registry import RegistryValidator


REGISTRIES = Path("archive/procurement_services/platform/registries")


def test_current_runtime_contract_references_are_valid() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert RegistryValidator().validate(catalog) == []

    ontology = catalog.runtime_contracts["company"]
    assert all(item.id != "representative" for item in ontology.object_types)
    legal_entity = next(item for item in ontology.object_types if item.id == "legal_entity")
    representative_names = next(item for item in legal_entity.properties if item.id == "representative_names")
    assert representative_names.collection == "list"
    legal_entity_properties = {item.id for item in legal_entity.properties}
    assert {
        "profile_observed_at",
        "latest_auditor_name",
        "latest_audit_opinion",
        "audit_information_observed_at",
    } <= legal_entity_properties
    assert all(item.id != "audit_report" for item in ontology.object_types)

    relationship = next(item for item in ontology.object_types if item.id == "organization_relationship")
    relationship_properties = {item.id for item in relationship.properties}
    assert "reference_date" in relationship_properties
    assert "effective_date" not in relationship_properties
    assert "related_organization_name" in relationship_properties

    link_ids = {item.id for item in ontology.link_types}
    assert "organization_relationship_has_reference_entity" in link_ids
    assert "organization_relationship_has_related_entity" in link_ids
    assert "organization_relationship_has_subject" not in link_ids
    assert "organization_relationship_has_object" not in link_ids
    disclosure = next(item for item in ontology.object_types if item.id == "venture_company_disclosure")
    assert disclosure.primary_key == "disclosure_id"
    assert {"business_registration_number", "status", "observed_at"} <= {
        item.id for item in disclosure.properties
    }
    disclosure_link = next(
        item
        for item in ontology.link_types
        if item.id == "business_registration_has_venture_company_disclosure"
    )
    assert disclosure_link.source == "business_registration"
    assert disclosure_link.target == "venture_company_disclosure"

    procurement = catalog.runtime_contracts["public_procurement"]
    participation = next(
        item for item in procurement.object_types if item.id == "contract_participation"
    )
    assert participation.primary_key == "participation_id"
    assert {
        "supplier_sequence",
        "business_registration_number",
        "supplier_role_name",
        "joint_contract_method_name",
        "participation_share_rate",
    } <= {item.id for item in participation.properties}
    assert "contract_participation_is_for_contract" in {
        item.id for item in procurement.link_types
    }




def test_reports_runtime_contract_reference_errors() -> None:
    catalog = deepcopy(RegistryLoader(REGISTRIES).load())
    ontology = catalog.runtime_contracts["company"]
    listing = next(item for item in ontology.object_types if item.id == "market_listing")
    market = next(item for item in listing.properties if item.id == "market")
    market.value_set = "missing_value_set"
    link = next(item for item in ontology.link_types if item.id == "legal_entity_has_market_listing")
    link.target = "missing_object_type"

    codes = {item.code for item in RegistryValidator().validate(catalog)}

    assert {
        "unknown_value_set",
        "unknown_link_object_type",
    } <= codes


def _write_runtime_contract(path: Path, contract_id: str, *, target: str | None = None) -> None:
    import yaml

    contract = {
        'id': contract_id,
        'name': contract_id,
        'description': 'Runtime contract fixture',
        'object_types': [{
            'id': 'item', 'name': 'Item', 'description': 'Runtime item', 'primary_key': 'id',
            'properties': [{'id': 'id', 'name': 'ID', 'description': 'Identity', 'data_type': 'string'}],
        }],
    }
    if target:
        contract['link_types'] = [{'id': 'references_item', 'description': 'Cross-contract link',
                                  'source': 'item', 'target': target}]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({'registry': {'version': '1.0.0', 'registered_at': '2026-10-12'},
                                   'runtime_contract': contract}), encoding='utf-8')


def test_one_domain_can_own_multiple_contract_namespaces(tmp_path: Path) -> None:
    root = tmp_path / 'registries'
    contracts = root / 'domains' / 'public_procurement' / 'runtime_contracts'
    _write_runtime_contract(contracts / 'public_procurement.yaml', 'public_procurement')
    _write_runtime_contract(contracts / 'assessment.yaml', 'assessment', target='public_procurement.item')

    catalog = RegistryLoader(root).load()

    assert set(catalog.runtime_contracts) == {'public_procurement', 'assessment'}
    assert RegistryValidator().validate(catalog) == []


def test_owned_contract_filename_must_identify_its_namespace(tmp_path: Path) -> None:
    root = tmp_path / 'registries'
    _write_runtime_contract(root / 'domains' / 'public_procurement' / 'runtime_contracts' / 'wrong.yaml',
                            'assessment')

    diagnostics = RegistryValidator().validate(RegistryLoader(root).load())

    assert [item.code for item in diagnostics] == ['runtime_contract_filename_mismatch']


def test_legacy_single_contract_releases_remain_readable(tmp_path: Path) -> None:
    root = tmp_path / 'registries'
    _write_runtime_contract(root / 'domains' / 'assessment' / 'runtime_contract.yaml', 'assessment')

    catalog = RegistryLoader(root).load()

    assert set(catalog.runtime_contracts) == {'assessment'}
    assert RegistryValidator().validate(catalog) == []


def test_duplicate_namespace_across_layouts_is_rejected(tmp_path: Path) -> None:
    import pytest
    from teoria.registry.loader import RegistryLoadError

    root = tmp_path / 'registries'
    _write_runtime_contract(root / 'runtime_contracts' / 'assessment.yaml', 'assessment')
    _write_runtime_contract(root / 'domains' / 'public_procurement' / 'runtime_contracts' / 'assessment.yaml',
                            'assessment')

    with pytest.raises(RegistryLoadError) as exc_info:
        RegistryLoader(root).load()

    assert [item.code for item in exc_info.value.diagnostics] == ['duplicate_runtime_contract']
