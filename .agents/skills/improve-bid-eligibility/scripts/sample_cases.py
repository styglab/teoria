#!/usr/bin/env python3
"""Read-only stratified sampler for bid-notice evaluation candidates."""

import argparse
import json
import os
import sys

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url-env", default="TEORIA_PIPELINE_DATA_DATABASE_URL")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--per-work-type", type=int, default=5)
    parser.add_argument("--seed", default="eligibility-eval-v1")
    args = parser.parse_args()
    if args.days < 1 or args.per_work_type < 1:
        parser.error("--days and --per-work-type must be positive")
    database_url = os.getenv(args.database_url_env)
    if not database_url:
        parser.error(f"environment variable {args.database_url_env} is not set")

    sql = """
    WITH candidates AS (
      SELECT n.notice_number, n.notice_order, n.work_type,
             n.notice_published_at, n.is_re_notice,
             count(d.document_id) AS document_count,
             count(d.document_id) FILTER (WHERE d.status <> 'stored') AS unavailable_count,
             count(d.document_id) FILTER (WHERE d.parse_status = 'unsupported') AS unsupported_count,
             row_number() OVER (
               PARTITION BY n.work_type
               ORDER BY md5(%s || n.notice_number || ':' || n.notice_order)
             ) AS sample_rank
      FROM public_procurement.bid_notices n
      LEFT JOIN public_procurement.bid_notice_documents d
        USING (notice_number, notice_order)
      WHERE n.notice_published_at >= now() - (%s * interval '1 day')
      GROUP BY n.notice_number, n.notice_order, n.work_type,
               n.notice_published_at, n.is_re_notice
    )
    SELECT notice_number, notice_order, work_type, notice_published_at,
           is_re_notice, document_count, unavailable_count, unsupported_count
    FROM candidates WHERE sample_rank <= %s
    ORDER BY work_type, sample_rank
    """
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(sql, (args.seed, args.days, args.per_work_type)).fetchall()
    keys = (
        "notice_number", "notice_order", "work_type", "notice_published_at",
        "is_re_notice", "document_count", "unavailable_count", "unsupported_count",
    )
    result = []
    for row in rows:
        item = dict(zip(keys, row, strict=True))
        item["notice_published_at"] = item["notice_published_at"].isoformat()
        result.append(item)
    json.dump({"seed": args.seed, "candidates": result}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
