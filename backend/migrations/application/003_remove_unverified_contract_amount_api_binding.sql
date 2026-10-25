DELETE FROM binding.ontology_bindings
 WHERE binding_id = '10000000-0000-4000-8000-000000000005'
   AND target_type = 'api_field'
   AND target_locator = 'provider://pps_contract/get_contract/response/cntrctAmt';

-- API field bindings are added only after the active Source Registry contract
-- verifies the provider's original response field. Example field names are not
-- authoritative metadata.
