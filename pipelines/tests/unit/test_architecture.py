import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[2] / "src" / "teoria_pipelines"
PLATFORM_INTEGRATION_MODULES = {"cli.py"}


def test_pipeline_runtime_does_not_import_platform() -> None:
    violations: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.name in PLATFORM_INTEGRATION_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "teoria" or name.startswith("teoria.") for name in names):
                violations.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
    assert violations == []
