ALTER TABLE public_procurement.bid_notices
    ADD COLUMN participation_restriction_region_code text,
    ADD COLUMN participation_restriction_region_name text;

ALTER TABLE public_procurement.bid_notice_participation_regions
    ADD COLUMN participation_region_code text;

UPDATE public_procurement.bid_notices
SET participation_restriction_region_code = source_payload->>'prtcptLmtRgnCd',
    participation_restriction_region_name = source_payload->>'prtcptLmtRgnNm'
WHERE source_payload ? 'prtcptLmtRgnCd'
   OR source_payload ? 'prtcptLmtRgnNm';

UPDATE public_procurement.bid_notice_participation_regions
SET participation_region_code = CASE trim(participation_region_name)
    WHEN '전국' THEN '00'
    WHEN '서울특별시' THEN '11'
    WHEN '부산광역시' THEN '26'
    WHEN '대구광역시' THEN '27'
    WHEN '인천광역시' THEN '28'
    WHEN '광주광역시' THEN '29'
    WHEN '대전광역시' THEN '30'
    WHEN '울산광역시' THEN '31'
    WHEN '세종특별자치시' THEN '36'
    WHEN '경기도' THEN '41'
    WHEN '강원도' THEN '42'
    WHEN '충청북도' THEN '43'
    WHEN '충청남도' THEN '44'
    WHEN '전라북도' THEN '45'
    WHEN '전라남도' THEN '46'
    WHEN '경상북도' THEN '47'
    WHEN '경상남도' THEN '48'
    WHEN '제주도' THEN '50'
    WHEN '제주특별자치도' THEN '50'
    WHEN '강원특별자치도' THEN '51'
    WHEN '전북특별자치도' THEN '52'
    WHEN '기타' THEN '99'
END
WHERE participation_region_code IS NULL;
