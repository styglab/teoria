import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "teoria"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_data_processing_uses_only_data_platform_services():
    paths = list((SOURCE_ROOT / "domains/goods/data_processing").rglob("*.py"))
    assert paths
    assert not [
        (str(path.relative_to(SOURCE_ROOT)), name)
        for path in paths
        for name in imports(path)
        if name.startswith("teoria.platform.")
        and not name.startswith("teoria.platform.data.operations.")
    ]


def test_data_infrastructure_does_not_import_feature_implementations():
    root = SOURCE_ROOT / "platform/data/operations"
    paths = [
        root / name
        for name in ("execution.py", "checkpoints.py", "persistence.py", "models.py")
    ]
    assert paths
    assert not [
        (str(p.relative_to(SOURCE_ROOT)), name)
        for p in paths
        for name in imports(p)
        if name.startswith(("teoria.domains.", "teoria.apps."))
    ]


def test_prefect_tasks_do_not_implement_postgres_access():
    paths = [
        path
        for area in ("platform", "domains")
        for path in (SOURCE_ROOT / area).rglob("*.py")
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                (
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Name)
                    and d.func.id == "task"
                )
                or (isinstance(d, ast.Name) and d.id == "task")
                for d in node.decorator_list
            )
            for node in ast.walk(ast.parse(path.read_text()))
        )
    ]
    assert paths
    assert not [
        (str(p.relative_to(SOURCE_ROOT)), name)
        for p in paths
        for name in imports(p)
        if name == "psycopg" or name.startswith("psycopg.")
    ]


def test_external_execution_adapters_do_not_import_features():
    paths = [
        p
        for package in ("provider_api", "codex")
        for p in (SOURCE_ROOT / "integrations" / package).rglob("*.py")
    ]
    assert paths
    assert not [
        (str(p.relative_to(SOURCE_ROOT)), name)
        for p in paths
        for name in imports(p)
        if name.startswith(("teoria.platform.", "teoria.apps."))
    ]


def test_active_proposals_do_not_eagerly_load_legacy_dictionary_writers():
    root = SOURCE_ROOT / "domains/goods/normalization/meaning_proposals"
    for path in root.glob("*.py"):
        # Only explicit runtime compatibility branches may import the v1 writers.
        for node in ast.parse(path.read_text()).body:
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(name and ".legacy_dictionary" in name for name in names), (
                path
            )


def test_profile_application_never_consumes_legacy_dictionary_authoring():
    root = SOURCE_ROOT / "domains/goods/normalization/application"
    assert not [
        (str(p.relative_to(SOURCE_ROOT)), name)
        for p in root.glob("*.py")
        for name in imports(p)
        if ".legacy_dictionary" in name
    ]


def test_process_composition_does_not_wire_local_definition_writers():
    root = SOURCE_ROOT / "entrypoints/composition"
    assert not [
        (str(p.relative_to(SOURCE_ROOT)), name)
        for p in root.glob("*.py")
        for name in imports(p)
        if name.startswith("teoria.domains.goods.expression_links.legacy")
    ]


def test_goods_dictionary_consumes_only_the_public_ontology_publication_contract():
    root = SOURCE_ROOT / "domains/goods/expression_links"
    assert not [
        (str(p.relative_to(SOURCE_ROOT)), name)
        for p in root.rglob("*.py")
        for name in imports(p)
        if name.startswith("teoria.platform.ontology.authoring")
        and name != "teoria.platform.ontology.authoring.publication_contracts"
    ]
