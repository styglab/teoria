ARG OPENMETADATA_VERSION=2.0.5
ARG OPENMETADATA_BASE_IMAGE=docker.getcollate.io/openmetadata/ingestion-base:${OPENMETADATA_VERSION}
FROM ${OPENMETADATA_BASE_IMAGE}

COPY --chown=openmetadata:openmetadata \
  deploy/compose/openmetadata/ingestion/teoria-postgres.yaml.example \
  /config/teoria-postgres.yaml
