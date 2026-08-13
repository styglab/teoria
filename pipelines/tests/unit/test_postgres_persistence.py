from unittest.mock import MagicMock, patch

from teoria_pipelines.persistence.postgres import PostgresStore


def test_parser_claim_reclaims_expired_processing_lease() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        PostgresStore("postgresql://unused").claim_documents_for_parsing(
            10, "2.1.1", max_attempts=3,
        )

    sql, parameters = connection.execute.call_args.args
    assert "parse_status='processing' AND updated_at <= now()-interval '1 hour'" in sql
    assert parameters == (3, "2.1.1", 10)


def test_extraction_selection_prioritizes_latest_service_notices() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        PostgresStore("postgresql://unused").list_notices_for_eligibility_extraction(10)

    sql, parameters = connection.execute.call_args.args
    assert (
        "ORDER BY CASE WHEN n.work_type='service' THEN 0 ELSE 1 END, "
        "n.notice_published_at DESC"
    ) in sql
    assert parameters == [3, 3, 10]
