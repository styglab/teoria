from teoria.metadata.openmetadata.mapper import page, table_detail


def test_maps_openmetadata_page_without_leaking_wire_shape() -> None:
    result = page({"data": [{"id": "1", "name": "contracts", "fullyQualifiedName": "svc.db.schema.contracts"}], "paging": {"total": 1}}, "table")
    assert result.total == 1
    assert result.items[0].reference.entity_type == "table"
    assert result.items[0].reference.fully_qualified_name == "svc.db.schema.contracts"


def test_maps_table_columns_and_glossary_terms() -> None:
    result = table_detail({
        "id": "1", "name": "contracts", "fullyQualifiedName": "svc.db.schema.contracts",
        "columns": [{"name": "amount", "dataType": "NUMERIC"}],
        "tags": [{"tagFQN": "계약.계약금액", "source": "Glossary"}, {"tagFQN": "PII", "source": "Classification"}],
        "testSuite": {"id": "suite-1", "name": "contracts.testSuite"},
    })
    assert result.columns[0]["name"] == "amount"
    assert result.glossary_terms == [{"tagFQN": "계약.계약금액", "source": "Glossary"}]
    assert result.test_suite == {"id": "suite-1", "name": "contracts.testSuite"}
