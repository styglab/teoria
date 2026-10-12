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


def test_execution_and_checkpoint_packages_do_not_import_domains() -> None:
    violations = []
    for package in ("execution", "checkpoints"):
        for path in (SOURCE_ROOT / package).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                if any(name.startswith("teoria_pipelines.domains") for name in names):
                    violations.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
    assert violations == []


def test_eligibility_validation_and_repair_have_no_orchestration_or_storage_imports() -> None:
    package = SOURCE_ROOT / "domains/public_procurement/bid_eligibility"
    paths = [package / "validation.py", package / "structured.py", *sorted((package / "repair").glob("*.py"))]
    forbidden = ("prefect", "psycopg", "subprocess", "teoria_pipelines.persistence", "teoria_pipelines.execution")
    violations = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            if any(name == prefix or name.startswith(prefix + ".") for name in names for prefix in forbidden):
                violations.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
    assert violations == []
