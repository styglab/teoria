from unittest.mock import patch

from teoria.admin.bid_check import BidCheckReader


class _Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value

    def fetchall(self):
        return self.value


class _Connection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return _Result({"count": 0} if len(self.calls) % 2 else [])


def test_list_notices_limits_base_rows_before_counting_requirements() -> None:
    connection = _Connection()
    with patch("teoria.admin.bid_check.psycopg.connect", return_value=connection):
        BidCheckReader("postgresql://test").list_notices()

    count_sql, page_sql = (call[0] for call in connection.calls)
    assert "LATERAL" not in count_sql
    assert "runtime_bid_notices" not in count_sql
    assert "WITH page AS MATERIALIZED" in page_sql
    assert "LIMIT %s OFFSET %s" in page_sql
    assert "runtime_bid_requirements" not in page_sql
    assert connection.calls[1][1] == (50, 0)


def test_list_notices_count_joins_extractions_only_when_filtered() -> None:
    connection = _Connection()
    with patch("teoria.admin.bid_check.psycopg.connect", return_value=connection):
        BidCheckReader("postgresql://test").list_notices(extraction_status="extracted")

    count_sql = connection.calls[0][0]
    assert "SELECT DISTINCT ON (e.notice_number,e.notice_order)" in count_sql
    assert "le.completeness IS NOT NULL" in count_sql
