DROP INDEX public_procurement.contracts_normalized_notice_status_idx;

CREATE INDEX contracts_normalized_notice_status_idx
    ON public_procurement.contracts (
        (CASE
            WHEN notice_number~'^[0-9]{13}$' AND right(notice_number,2)='00'
                THEN left(notice_number,length(notice_number)-2)
            ELSE NULLIF(notice_number,'')
         END),
        concluded_date DESC,
        updated_at DESC
    );
