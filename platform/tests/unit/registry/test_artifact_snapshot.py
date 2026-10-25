from pathlib import Path
from copy import deepcopy

from teoria.registry.artifact_snapshot import select_registry_bindings
from teoria.registry.loader import RegistryCatalog


def test_snapshot_omits_retired_targets_and_preserves_metadata_and_review_history():
    catalog = RegistryCatalog(root=Path('.'), sources={}, source_paths={}, data_types={})
    bindings = [
        {'target_type': 'capability_output', 'capability_id': 'retired', 'status': 'approved'},
        {'target_type': 'api_field', 'api_source_id': 'retired_api', 'status': 'approved'},
        {'target_type': 'data_asset', 'target_locator': 'openmetadata://table/id', 'status': 'approved'},
        {'target_type': 'glossary_term', 'target_locator': 'openmetadata://term/id', 'status': 'approved'},
    ]
    original = deepcopy(bindings)
    assert select_registry_bindings(catalog, bindings) == bindings[2:]
    assert bindings == original


def test_snapshot_does_not_rewrite_versions_of_retained_targets():
    catalog = RegistryCatalog(root=Path('.'), sources={'active_api': object()},
                              source_paths={}, data_types={}, capabilities={'active': object()})
    bindings = [
        {'target_type': 'capability', 'capability_id': 'active',
         'capability_registry_version': 'old_release', 'status': 'approved'},
        {'target_type': 'api_field', 'api_source_id': 'active_api', 'status': 'approved'},
    ]
    assert select_registry_bindings(catalog, bindings) == bindings
    assert bindings[0]['capability_registry_version'] == 'old_release'
