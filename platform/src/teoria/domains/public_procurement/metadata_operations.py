"""Read the public-procurement pipeline output contract, without ingestion access."""

import psycopg
from psycopg.rows import dict_row


class AssetCollectionReader:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def __call__(self, database: str, schema: str, relation: str) -> list[dict]:
        with psycopg.connect(self.database_url, row_factory=dict_row,
                             connect_timeout=3, options="-c default_transaction_read_only=on -c statement_timeout=3000") as connection:
            return connection.execute(
                "SELECT * FROM public_procurement.runtime_asset_collection_status "
                "WHERE database_name=%s AND schema_name=%s AND relation_name=%s ORDER BY pipeline_id",
                (database, schema, relation),
            ).fetchall()
