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


def test_features_and_integrations_do_not_depend_on_process_entrypoints():
    paths = [
        *SOURCE.joinpath("features").rglob("*.py"),
        *SOURCE.joinpath("integrations").rglob("*.py"),
    ]
    assert paths
    assert not [
        (str(p.relative_to(SOURCE)), name)
        for p in paths
        for name in imports(p)
        if name == "teoria.entrypoints" or name.startswith("teoria.entrypoints.")
    ]


def test_feature_dependency_graph_is_acyclic():
    graph = defaultdict(set)
    for path in SOURCE.joinpath("features").rglob("*.py"):
        owner = path.relative_to(SOURCE).parts[1]
        for name in imports(path):
            parts = name.split(".")
            if (
                len(parts) >= 3
                and parts[:2] == ["teoria", "features"]
                and parts[2] != owner
            ):
                graph[owner].add(parts[2])
    assert graph
    visited, visiting = set(), []

    def visit(owner):
        assert owner not in visiting, "Feature cycle: " + " -> ".join(
            [*visiting, owner]
        )
        if owner in visited:
            return
        visiting.append(owner)
        for target in graph[owner].copy():
            visit(target)
        visiting.pop()
        visited.add(owner)

    for owner in list(graph):
        visit(owner)


def test_connector_contract_loading_does_not_depend_on_prefect():
    root = SOURCE / "integrations/data_operations"
    paths = [
        root / name
        for name in ("loader.py", "models.py", "validator.py", "diagnostics.py")
    ] + list((root / "schema").rglob("*.py"))
    assert paths
    assert not [
        (str(p.relative_to(SOURCE)), name)
        for p in paths
        for name in imports(p)
        if name.startswith(("prefect", "teoria.integrations.prefect"))
    ]


def test_profile_and_ontology_policies_have_no_inline_sql():
    paths = [
        SOURCE / "features/goods_normalization/profiles/service.py",
        SOURCE / "features/semantic_modeling/ontology/service.py",
        SOURCE
        / "features/goods_normalization/candidates/semantic_operation_service.py",
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
