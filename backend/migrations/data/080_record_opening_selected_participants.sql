-- NULL preserves unverified legacy observations; never infer completion from old counts.
ALTER TABLE ingestion.bid_opening_collection_status
    ADD COLUMN selected_business_numbers text[];
COMMENT ON COLUMN ingestion.bid_opening_collection_status.selected_business_numbers IS
    'Sorted unique top-10/winner business numbers from a fully validated opening response; NULL means unverified.';
