CREATE TABLE public_procurement.bid_eligibility_gold_reviews (
    review_id uuid PRIMARY KEY,
    extraction_id uuid NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'gold', 'rejected')),
    completeness_confirmed boolean NOT NULL DEFAULT false,
    reviewed_requirements jsonb NOT NULL,
    reviewer text NOT NULL,
    notes text,
    source_fingerprint text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (extraction_id)
        REFERENCES public_procurement.bid_eligibility_extractions(extraction_id) ON DELETE CASCADE,
    CHECK (status <> 'gold' OR completeness_confirmed)
);

COMMENT ON TABLE public_procurement.bid_eligibility_gold_reviews IS
    'Admin 검토자가 원문 Evidence와 누락 여부를 확인한 불변 추출 버전별 Gold 후보/승인 기록';
COMMENT ON COLUMN public_procurement.bid_eligibility_gold_reviews.reviewed_requirements IS
    '원본 추출을 변경하지 않고 보존하는 검토·수정 완료 Requirement JSON snapshot';
COMMENT ON COLUMN public_procurement.bid_eligibility_gold_reviews.source_fingerprint IS
    '검토 대상 extraction의 input_fingerprint; 다른 입력 버전으로 Gold가 잘못 승계되는 것을 방지';

CREATE INDEX bid_eligibility_gold_reviews_status_idx
    ON public_procurement.bid_eligibility_gold_reviews (status, updated_at DESC);

GRANT SELECT ON public_procurement.bid_eligibility_gold_reviews TO teoria_runtime;
