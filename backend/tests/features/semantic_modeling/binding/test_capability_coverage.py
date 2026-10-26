from pathlib import Path

from teoria.features.semantic_modeling.binding.coverage import build_capability_binding_coverage
from teoria.features.semantic_modeling.registry.loader import RegistryLoader


ROOT = (Path(__file__).resolve().parents[5] / 'backend')


def test_capability_coverage_reports_bound_and_unbound_contract_fields() -> None:
    catalog = RegistryLoader(Path("backend/tests/fixtures/registry")).load()
    report = build_capability_binding_coverage(
        catalog,
        [
            {
                "capability_id": "get_record",
                "capability_target_scope": "output",
                "capability_field_path": "example.record",
            }
        ],
    )

    item = next(
        row for row in report["items"]
        if row["capability_id"] == "get_record"
    )
    assert item["status"] == "partial"
    assert item["outputs"]["bound"] == 1
    assert report["summary"]["capability_count"] == 2
    assert report["summary"]["capability_bound_count"] == 1
