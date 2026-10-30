"""Read-only bounded selection from restored goods notices, never a collector."""
from psycopg.rows import dict_row
from teoria.integrations.data_operations.persistence.connection import connect
from teoria.integrations.data_operations.settings import bootstrap_pipeline_settings


async def notice_candidates(classification_code, date_from, date_to, limit):
    async with connect(bootstrap_pipeline_settings().data_database_url, row_factory=dict_row) as connection:
        await connection.execute("SET LOCAL statement_timeout = '30s'")
        return await(await connection.execute('''
            SELECT n.notice_number,n.notice_order,n.notice_published_at,n.source_payload,n.source_record_hash,
                   n.purchase_items,n.procurement_classification_number
            FROM public_procurement.bid_notices n
            JOIN public_procurement.bid_notice_latest_versions v
              ON v.notice_number=n.notice_number AND v.notice_order=n.notice_order
            WHERE n.work_type='goods' AND n.notice_kind_name IS DISTINCT FROM '취소공고'
              AND n.notice_published_at >= %s AND n.notice_published_at < %s
              AND (n.procurement_classification_number=%s OR EXISTS (
                SELECT 1 FROM jsonb_array_elements(COALESCE(n.purchase_items,'[]'::jsonb)) i
                WHERE i->>'code'=%s))
            ORDER BY n.notice_published_at DESC,n.notice_number DESC,n.notice_order DESC
            LIMIT %s''',(date_from,date_to,classification_code,classification_code,limit))).fetchall()
