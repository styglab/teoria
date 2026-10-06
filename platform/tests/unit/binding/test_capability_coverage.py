from pathlib import Path

from teoria.binding.coverage import build_capability_binding_coverage
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


def test_capability_coverage_reports_bound_and_unbound_contract_fields() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    report = build_capability_binding_coverage(
        catalog,
        [
            {
                "capability_id": "get_public_procurement_contract",
                "capability_target_scope": "output",
                "capability_field_path": "public_procurement.contract",
            }
        ],
    )

    item = next(
        row for row in report["items"]
        if row["capability_id"] == "get_public_procurement_contract"
    )
    assert item["status"] == "partial"
    assert item["outputs"]["bound"] == 1
    assert report["summary"]["capability_count"] == 52
    assert report["summary"]["capability_bound_count"] == 1
