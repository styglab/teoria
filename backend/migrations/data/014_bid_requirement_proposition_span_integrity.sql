ALTER TABLE public_procurement.bid_eligibility_requirements
    DROP CONSTRAINT bid_eligibility_requirements_proposition_span_check,
    ADD CONSTRAINT bid_eligibility_requirements_proposition_span_check CHECK (
        (proposition_text IS NULL AND proposition_start IS NULL AND proposition_end IS NULL)
        OR (
            proposition_text IS NOT NULL
            AND proposition_start IS NOT NULL
            AND proposition_end IS NOT NULL
            AND proposition_start >= 0
            AND proposition_end > proposition_start
            AND proposition_end <= char_length(original_text)
            AND substring(
                original_text
                FROM proposition_start + 1
                FOR proposition_end - proposition_start
            ) = proposition_text
        )
    );
