#!/bin/sh
set -eu

if [ ! -s /keys/private.pem ] || [ ! -s /keys/public.pem ]; then
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out /keys/private.pem
    openssl pkey -in /keys/private.pem -pubout -out /keys/public.pem
    chmod 600 /keys/private.pem
    chmod 644 /keys/public.pem
fi

/opa check --strict /policy_source
/opa test /policy_source
/opa build \
    --bundle /policy_source \
    --ignore '*_test.rego' \
    --revision "${TEORIA_OPA_BUNDLE_REVISION:-development}" \
    --signing-key /keys/private.pem \
    --verification-key-id teoria \
    --claims-file /config/signing_claims.json \
    --output /bundle/teoria.tar.gz
