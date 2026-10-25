ALTER TABLE ingestion.pipeline_runs
    ADD COLUMN award_count integer NOT NULL DEFAULT 0,
    ADD COLUMN opening_participant_count integer NOT NULL DEFAULT 0;

CREATE TABLE public_procurement.bid_awards (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    bid_classification_number text NOT NULL,
    rebid_number text NOT NULL,
    work_type text NOT NULL CHECK (work_type IN ('goods', 'construction', 'service', 'foreign')),
    notice_division_code text,
    notice_name text,
    participant_count integer,
    winner_name text,
    winner_business_registration_number text,
    winner_representative_name text,
    winner_address text,
    winner_telephone_number text,
    winning_amount numeric,
    winning_rate numeric,
    opening_at timestamptz,
    demand_organization_code text,
    demand_organization_name text,
    source_registered_at timestamptz,
    final_award_date date,
    winner_manager_name text,
    source_record_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_number, notice_order, bid_classification_number, rebid_number)
);

CREATE TABLE public_procurement.bid_opening_participants (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    bid_classification_number text NOT NULL,
    rebid_number text NOT NULL,
    business_registration_number text NOT NULL,
    opening_result_type_name text,
    opening_rank integer,
    participant_name text,
    representative_name text,
    bid_amount numeric,
    bid_rate numeric,
    remark text,
    trade_bid_amount_url text,
    draw_number_1 text,
    draw_number_2 text,
    bid_at timestamptz,
    bid_price_evaluation_score numeric,
    technical_evaluation_raw_score numeric,
    technical_evaluation_score numeric,
    total_evaluation_score numeric,
    source_record_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        notice_number, notice_order, bid_classification_number,
        rebid_number, business_registration_number
    )
);

CREATE INDEX bid_awards_opening_at_idx ON public_procurement.bid_awards (opening_at DESC);
CREATE INDEX bid_awards_final_award_date_idx ON public_procurement.bid_awards (final_award_date DESC);
CREATE INDEX bid_awards_winner_business_number_idx
    ON public_procurement.bid_awards (winner_business_registration_number);
CREATE INDEX bid_opening_participants_business_number_idx
    ON public_procurement.bid_opening_participants (business_registration_number);
CREATE INDEX bid_opening_participants_notice_idx
    ON public_procurement.bid_opening_participants (
        notice_number, notice_order, bid_classification_number, rebid_number
    );
