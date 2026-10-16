from pathlib import Path


def test_contract_relationship_context_has_company_first_lookup_index() -> None:
    migration = (
        Path(__file__).parents[5]
        / "database"
        / "migrations"
        / "068_optimize_contract_relationship_company_lookup.sql"
    ).read_text()

    assert "contract_event_company_ledger_company_date_idx" in migration
    assert "company_number, first_contract_date, organization_code" in " ".join(
        migration.split()
    )
