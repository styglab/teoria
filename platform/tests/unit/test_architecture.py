import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[2] / "src" / "teoria"


def test_runtime_and_context_orchestration_do_not_import_domain_implementations():
    paths = [
        *sorted((SOURCE_ROOT / "runtime/capability").glob("*.py")),
        SOURCE_ROOT / "context/service.py",
        SOURCE_ROOT / "context/query.py",
    ]
    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "teoria.domains" or name.startswith("teoria.domains.") for name in names):
                violations.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
    assert violations == []


def test_common_registry_and_ontology_modules_do_not_own_procurement_rules():
    paths = [*sorted((SOURCE_ROOT / 'registry/validation').glob('*.py')),
             *sorted((SOURCE_ROOT / 'ontology').glob('*.py'))]
    violations = []
    for path in paths:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('teoria.domains.'):
                violations.append(f'{path.relative_to(SOURCE_ROOT)}:{node.lineno}')
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if 'public_procurement.' in node.value or node.value == 'procurement_supplier_registered':
                    violations.append(f'{path.relative_to(SOURCE_ROOT)}:{node.lineno}')
    assert violations == []


def test_canonical_code_does_not_depend_on_compatibility_paths():
    legacy_paths = (
        'teoria.config',
        'teoria.admin.semantic_api',
        'teoria.runtime.mapping.functions',
        'teoria.domains.public_procurement.market_context',
        'teoria.domains.public_procurement.ontology_profiling',
        'teoria.domains.public_procurement.ontology_shadow',
        'teoria.domains.public_procurement.bid_eligibility.processor',
    )
    violations = []
    for path in SOURCE_ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            modules = [node.module] if isinstance(node, ast.ImportFrom) and node.module else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            )
            if any(module == legacy or module.startswith(legacy + '.')
                   for module in modules for legacy in legacy_paths):
                violations.append(f'{path.relative_to(SOURCE_ROOT)}:{node.lineno}')
    assert violations == []
