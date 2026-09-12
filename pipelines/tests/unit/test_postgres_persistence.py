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
    assert (
        "parse_status IN ('parsed','unsupported') "
        "AND parser_version IS DISTINCT FROM %s"
    ) in sql
    assert "CASE WHEN c.parser_version_changed THEN 1" in sql
    assert parameters == ("2.1.1", 3, "2.1.1", 10)


def test_extraction_selection_prioritizes_latest_active_notice_revision() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        PostgresStore("postgresql://unused").list_notices_for_eligibility_extraction(10)

    sql, parameters = connection.execute.call_args.args
    assert "n.notice_kind_name IS DISTINCT FROM '취소공고'" in sql
    assert "COALESCE(n.notice_kind_name, '') !~ '(평가|개찰|낙찰|계약).*(결과|결정)'" in sql
    assert "COALESCE(n.notice_name, '') !~" in sql
    assert "FROM public_procurement.bid_notices newer" in sql
    assert "ORDER BY n.notice_published_at DESC NULLS LAST" in sql
    assert parameters == [3, 3, 10]


def test_eligibility_claim_uses_one_hour_lease() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (1,)

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        claimed = PostgresStore("postgresql://unused").claim_eligibility_extraction(
            {"notice_number": "R1", "notice_order": "000"}, "fingerprint", "2.3.15"
        )

    sql, parameters = connection.execute.call_args.args
    assert claimed is True
    assert "status='processing'" in sql
    assert "started_at<=now()-interval '1 hour'" in sql
    assert parameters[1:] == ("R1", "000", "fingerprint", "2.3.15")
