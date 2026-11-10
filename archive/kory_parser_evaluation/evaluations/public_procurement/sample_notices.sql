
WITH candidates AS (
 SELECT n.notice_number,n.notice_order,n.work_type,n.notice_published_at,
 n.notice_organization_code,n.notice_name,
 (SELECT jsonb_agg(jsonb_build_object('slot',i,'file_name',n.source_payload->>('ntceSpecFileNm'||i),'url',n.source_payload->>('ntceSpecDocUrl'||i)) ORDER BY i)
 FROM generate_series(1,10)i WHERE nullif(n.source_payload->>('ntceSpecDocUrl'||i),'') IS NOT NULL) AS attachments
 FROM public_procurement.bid_notices n
 WHERE n.notice_published_at>=%(from_date)s::timestamptz
 AND n.notice_published_at<%(to_date)s::timestamptz
 AND n.notice_published_at<=now()
 AND n.notice_kind_name IS DISTINCT FROM '취소공고'
 AND NOT (n.notice_number = ANY(%(excluded_notice_numbers)s::text[]))
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY work_type ORDER BY md5(notice_number||':'||notice_order||':'||%(seed)s)) AS sample_rank
 FROM candidates WHERE attachments IS NOT NULL
)
SELECT notice_number,notice_order,work_type,notice_published_at,notice_organization_code,notice_name,attachments
FROM ranked WHERE sample_rank<=%(frame_limit)s ORDER BY work_type,sample_rank
