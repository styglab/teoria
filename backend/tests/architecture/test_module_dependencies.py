"""Enforce direction and acyclic dependencies between the actual feature packages."""

import ast
from collections import defaultdict
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/teoria"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_implementation_dependencies_point_toward_platform():
    forbidden = {
        "platform": ("teoria.domains", "teoria.apps", "teoria.examples", "teoria.entrypoints"),
        "domains": ("teoria.apps", "teoria.examples", "teoria.entrypoints"),
        "integrations": ("teoria.domains", "teoria.apps", "teoria.examples", "teoria.entrypoints"),
    }
    for owner, prefixes in forbidden.items():
        paths = list((SOURCE / owner).rglob("*.py"))
        assert paths
        assert not [
            (str(p.relative_to(SOURCE)), name)
            for p in paths
            for name in imports(p)
            if name.startswith(prefixes)
        ]


def test_platform_module_dependency_graph_is_acyclic():
    graph = defaultdict(set)
    for path in (SOURCE / "platform").rglob("*.py"):
        relative = path.relative_to(SOURCE).parts
        owner = (
            ".".join(relative[1:3])
            if relative[1] in {"data", "ontology"} and len(relative) > 3
            else relative[1]
        )
        for name in imports(path):
            parts = name.split(".")
            if len(parts) >= 3 and parts[:2] == ["teoria", "platform"]:
                target = (
                    ".".join(parts[2:4])
                    if parts[2] in {"data", "ontology"} and len(parts) > 3
                    else parts[2]
                )
                if target != owner:
                    graph[owner].add(target)
    assert graph
    visited, visiting = set(), []

    def visit(owner):
        assert owner not in visiting, "Module cycle: " + " -> ".join([*visiting, owner])
        if owner in visited:
            return
        visiting.append(owner)
        for target in graph[owner].copy():
            visit(target)
        visiting.pop()
        visited.add(owner)

    for owner in list(graph):
        visit(owner)


def test_apps_do_not_own_sql_or_database_connections():
    paths = list((SOURCE / "apps").rglob("*.py"))
    assert paths
    for path in paths:
        assert not [
            name
            for name in imports(path)
            if name.startswith(
                (
                    "teoria.integrations.data_database",
                    "teoria.integrations.application_database",
                )
            )
            or name.endswith((".repository", "_repository"))
        ]
        assert not [
            n
            for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in {"execute", "executemany"}
        ]


def test_connector_contract_loading_does_not_depend_on_prefect():
    root = SOURCE / "platform/data/operations"
    paths = [
        root / name for name in ("loader.py", "models.py", "validator.py", "schema.py")
    ] + list((root / "schema").rglob("*.py"))
    assert paths
    assert not [
        (str(p.relative_to(SOURCE)), name)
        for p in paths
        for name in imports(p)
        if name.startswith(("prefect", "teoria.integrations.prefect"))
    ]


def test_published_ontology_contract_is_independent_of_data_sources_and_authoring_services():
    path = SOURCE / "platform/ontology/authoring/publication_contracts.py"
    assert not [
        name
        for name in imports(path)
        if name.startswith(
            ("teoria.integrations", "teoria.entrypoints", "httpx", "psycopg", "prefect")
        )
        or (
            name.startswith("teoria.")
            and name != "teoria.platform.ontology.authoring.models"
        )
    ]


def test_ontology_review_contract_has_no_authoring_or_source_io_dependencies():
    path = SOURCE / "platform/ontology/authoring/review_contracts.py"
    assert not [
        name
        for name in imports(path)
        if name.startswith(
            ("teoria.integrations", "teoria.entrypoints", "httpx", "psycopg", "prefect")
        )
        or (
            name.startswith("teoria.")
            and name != "teoria.platform.ontology.authoring.publication_contracts"
        )
    ]


def test_profile_and_ontology_policies_have_no_inline_sql():
    paths = [
        SOURCE / "domains/goods/normalization/profiles/service.py",
        SOURCE / "platform/ontology/authoring/service.py",
        SOURCE / "domains/goods/normalization/candidates/semantic_operation_service.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text())
        assert not [
            (node.lineno, node.func.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "executemany"}
        ]


def test_extraction_does_not_import_semantic_application_or_workflow_implementations():
    root = SOURCE / "domains/goods/data_processing"
    paths = list(root.rglob("*.py"))
    assert paths
    forbidden = (
        "teoria.domains.goods.workflows",
        "teoria.domains.goods.normalization",
        "teoria.domains.goods.expression_links",
        "teoria.apps",
    )
    assert not [
        (str(path.relative_to(SOURCE)), name)
        for path in paths
        for name in imports(path)
        if name.startswith(forbidden)
    ]


def test_old_feature_root_is_removed():
    assert not (SOURCE / "features").exists()
    frontend = SOURCE.parents[2] / "frontend/src"
    assert frontend.exists()
    assert not (frontend / "features").exists()


def test_frontend_platform_does_not_import_examples():
    import re
    frontend = SOURCE.parents[2] / "frontend/src"
    for path in (frontend / "platform").rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
            continue
        imports = re.findall(r'(?:from\s+|import\s*\()\s*[\"\']([^\"\']+)', path.read_text())
        for name in imports:
            if name.startswith("."):
                target = (path.parent / name).resolve()
                assert not target.is_relative_to(frontend / "examples"), str(path)
