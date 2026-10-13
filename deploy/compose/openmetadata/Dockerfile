ARG OPENMETADATA_VERSION=2.0.5
FROM docker.getcollate.io/openmetadata/ingestion-base:${OPENMETADATA_VERSION}

COPY --chown=openmetadata:openmetadata \
  deploy/compose/openmetadata/ingestion/teoria-postgres.yaml.example \
  /config/teoria-postgres.yaml
