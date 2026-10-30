ARG MINIO_CLIENT_IMAGE=quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z
FROM ${MINIO_CLIENT_IMAGE}
COPY initialize_specification_storage.sh /initialize_specification_storage.sh
ENTRYPOINT ["/bin/sh", "/initialize_specification_storage.sh"]
