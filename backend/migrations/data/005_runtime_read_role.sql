GRANT CONNECT ON DATABASE teoria_data TO teoria_runtime;
GRANT USAGE ON SCHEMA public_procurement TO teoria_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA public_procurement TO teoria_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE teoria_pipeline IN SCHEMA public_procurement
    GRANT SELECT ON TABLES TO teoria_runtime;
