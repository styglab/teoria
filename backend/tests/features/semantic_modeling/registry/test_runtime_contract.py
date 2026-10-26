from pathlib import Path

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.registry.validation.registry import RegistryValidator


REGISTRIES = Path("backend/tests/fixtures/registry")








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
    from teoria.features.semantic_modeling.registry.loader import RegistryLoadError

    root = tmp_path / 'registries'
    _write_runtime_contract(root / 'runtime_contracts' / 'assessment.yaml', 'assessment')
    _write_runtime_contract(root / 'domains' / 'public_procurement' / 'runtime_contracts' / 'assessment.yaml',
                            'assessment')

    with pytest.raises(RegistryLoadError) as exc_info:
        RegistryLoader(root).load()

    assert [item.code for item in exc_info.value.diagnostics] == ['duplicate_runtime_contract']


def test_reference_validation_rejects_unknown_property_type_and_link_target():
    catalog = RegistryLoader(REGISTRIES).load()
    contract = catalog.runtime_contracts["example"]
    contract.object_types[0].properties[0].data_type = "missing_type"
    contract.link_types[0].target = "missing_object"
    codes = {item.code for item in RegistryValidator().validate(catalog)}
    assert {"unknown_data_type", "unknown_link_object_type"} <= codes
