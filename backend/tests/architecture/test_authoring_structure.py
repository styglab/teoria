"""Protect product boundaries after the Python projects have been consolidated."""
import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'teoria'


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_runtime_does_not_import_vertical_features():
    root = SOURCE_ROOT / 'features/runtime'
    paths = list(root.rglob('*.py'))
    assert paths
    forbidden = ('teoria.features.specification_processing',
                 'teoria.features.goods_normalization', 'teoria.features.legal_information')
    assert not [(str(p.relative_to(SOURCE_ROOT)), name)
                for p in paths for name in imports(p) if name.startswith(forbidden)]


def test_semantic_modeling_does_not_own_procurement_rules():
    root = SOURCE_ROOT / 'features/semantic_modeling'
    paths = list((root / 'registry/validation').rglob('*.py')) + list((root / 'ontology').glob('*.py'))
    assert paths
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in paths for name in imports(p)
                if name.startswith(('teoria.features.specification_processing', 'teoria.features.goods_normalization'))]
    for p in paths:
        constants = [n.value for n in ast.walk(ast.parse(p.read_text()))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any('public_procurement.' in v or v == 'procurement_supplier_registered' for v in constants)


def test_active_source_has_no_retired_python_namespaces():
    forbidden = ('teoria_pipelines', 'teoria_mcp', 'teoria_provider_api',
                 'teoria_goods_normalization', 'teoria_codex_inference', 'teoria.domains', 'archive')
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in SOURCE_ROOT.rglob('*.py')
                for name in imports(p)
                if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden)]


def test_mcp_only_uses_runtime_http_and_protocol_dependencies():
    paths = list((SOURCE_ROOT / 'integrations/runtime_http').rglob('*.py')) + [SOURCE_ROOT / 'entrypoints/mcp.py']
    assert paths
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in paths for name in imports(p)
                if name.startswith(('teoria.features.', 'teoria.integrations.application_database',
                                    'teoria.integrations.data_operations', 'psycopg', 'sqlalchemy'))]
