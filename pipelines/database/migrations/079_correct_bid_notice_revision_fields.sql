DO $$
DECLARE definition text;
DECLARE updated_definition text;
BEGIN
  SELECT pg_get_viewdef('public_procurement.runtime_bid_notices'::regclass,true)
  INTO definition;

  updated_definition := replace(
    definition,
    'base.root_bid_notice_id AS original_notice_id',
    '(COALESCE(base.lineage_notices,''[]'')::jsonb -> 0 ->> ''bid_notice_id'') AS original_notice_id'
  );
  updated_definition := replace(
    updated_definition,
    'lineage_current.revision_number,',
    'COALESCE((SELECT (member.position-1)::integer FROM '
      || 'jsonb_array_elements(COALESCE(base.lineage_notices,''[]'')::jsonb) '
      || 'WITH ORDINALITY member(item,position) WHERE member.item->>''bid_notice_id''='
      || 'base.bid_notice_id LIMIT 1),0) AS revision_number,'
  );

  IF updated_definition=definition THEN
    RAISE EXCEPTION 'runtime_bid_notices revision expressions were not found';
  END IF;
  EXECUTE 'CREATE OR REPLACE VIEW public_procurement.runtime_bid_notices AS '
    || updated_definition;
END $$;
