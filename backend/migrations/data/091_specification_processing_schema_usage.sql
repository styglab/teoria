-- Table privileges from 090 also require schema access for the execution roles.
GRANT USAGE ON SCHEMA public_procurement TO teoria_pipeline,teoria_runtime;
