#!/bin/sh
set -eu
: "${MINIO_ROOT_USER:?required}" "${MINIO_ROOT_PASSWORD:?required}"
: "${SPECIFICATION_WORKER_USER:?required}" "${SPECIFICATION_WORKER_PASSWORD:?required}"
: "${SPECIFICATION_API_USER:?required}" "${SPECIFICATION_API_PASSWORD:?required}"
mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing local/teoria-models >/dev/null
mc mb --ignore-existing local/teoria-artifacts >/dev/null
mc version enable local/teoria-artifacts >/dev/null
cat >/tmp/specification_worker.json <<'JSON'
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::teoria-artifacts/specification_inputs/*","arn:aws:s3:::teoria-artifacts/specification_processing/*","arn:aws:s3:::teoria-artifacts/legacy/*"]},
 {"Effect":"Allow","Action":["s3:PutObject"],"Resource":["arn:aws:s3:::teoria-artifacts/specification_processing/*"]}
]}
JSON
cat >/tmp/specification_api.json <<'JSON'
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::teoria-artifacts/specification_inputs/*","arn:aws:s3:::teoria-artifacts/specification_processing/*","arn:aws:s3:::teoria-artifacts/legacy/*"]},
 {"Effect":"Allow","Action":["s3:PutObject"],"Resource":["arn:aws:s3:::teoria-artifacts/specification_inputs/*"]}
]}
JSON
mc admin policy create local teoria_specification_worker /tmp/specification_worker.json >/dev/null
mc admin policy create local teoria_specification_api /tmp/specification_api.json >/dev/null
mc admin user add local "$SPECIFICATION_WORKER_USER" "$SPECIFICATION_WORKER_PASSWORD" >/dev/null
mc admin user add local "$SPECIFICATION_API_USER" "$SPECIFICATION_API_PASSWORD" >/dev/null
mc admin policy attach local teoria_specification_worker --user "$SPECIFICATION_WORKER_USER" >/dev/null
mc admin policy attach local teoria_specification_api --user "$SPECIFICATION_API_USER" >/dev/null
printf 'Specification storage initialized.\n'
