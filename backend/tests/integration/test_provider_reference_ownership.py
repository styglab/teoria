"""A shared evidence directory must preserve Source/Connector authority."""
from pathlib import Path
import shutil

import yaml

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.registry.validation.registry import RegistryValidator
from teoria.integrations.data_operations.loader import PipelineLoader
from teoria.integrations.data_operations.validator import PipelineValidator

BACKEND = Path(__file__).resolve().parents[2]


def test_shared_provider_library_keeps_connector_evidence_out_of_runtime_sources():
    runtime = RegistryLoader(BACKEND / 'registries').load()
    collection = PipelineLoader(BACKEND).load()
    assert 'moleg_law_api' not in runtime.references
    assert collection.references['moleg_law_api'].target == 'connector'
    assert RegistryValidator().validate(runtime) == []
    assert PipelineValidator().validate(collection) == []


def test_unregistered_source_reference_remains_an_error(tmp_path):
    shutil.copytree(BACKEND / 'registries', tmp_path / 'registries')
    reference = tmp_path / 'references/providers/test/unknown_source'
    reference.mkdir(parents=True)
    (reference / 'api.md').write_text('Provider reference')
    (reference / 'metadata.yaml').write_text(yaml.safe_dump({
        'status': 'active', 'target': 'source', 'provider': 'Test',
        'source': 'unknown_source', 'title': 'API reference', 'retrieved_at': '2026-10-25',
        'files': [{'path': 'api.md', 'format': 'markdown'}], 'registry': 'registries/sources/unknown_source.yaml',
    }))
    catalog = RegistryLoader(tmp_path / 'registries').load()
    diagnostics = RegistryValidator().validate(catalog)
    assert 'unknown_reference_target' in {item.code for item in diagnostics}
