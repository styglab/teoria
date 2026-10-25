import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'teoria'


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_document_processing_only_uses_published_goods_contracts():
    paths = list((SOURCE_ROOT / 'features/specification_processing').rglob('*.py'))
    assert paths
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in paths for name in imports(p)
                if name.startswith('teoria.features.')
                and not name.startswith(('teoria.features.specification_processing',
                                         'teoria.features.goods_normalization.contracts'))]


def test_data_infrastructure_does_not_import_feature_implementations():
    root = SOURCE_ROOT / 'integrations/data_operations'
    paths = [p for package in ('execution', 'checkpoints', 'persistence')
             for p in (root / package).rglob('*.py')] + [root / 'models.py']
    assert paths
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in paths for name in imports(p)
                if name.startswith('teoria.features.')]


def test_prefect_tasks_do_not_implement_postgres_access():
    paths = list((SOURCE_ROOT / 'features').rglob('*tasks.py'))
    assert paths
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in paths for name in imports(p)
                if name == 'psycopg' or name.startswith('psycopg.')]


def test_external_execution_adapters_do_not_import_features():
    paths = [p for package in ('provider_api', 'codex')
             for p in (SOURCE_ROOT / 'integrations' / package).rglob('*.py')]
    assert paths
    assert not [(str(p.relative_to(SOURCE_ROOT)), name) for p in paths for name in imports(p)
                if name.startswith('teoria.features.')]
