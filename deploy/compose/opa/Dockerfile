FROM openpolicyagent/opa:1.21.1-debug AS opa

FROM alpine:3.22 AS runtime
RUN apk add --no-cache ca-certificates curl su-exec \
    && addgroup -g 10001 opa \
    && adduser -D -u 10001 -G opa opa \
    && mkdir -p /var/lib/opa \
    && chown opa:opa /var/lib/opa
COPY --from=opa /opa /opa
COPY deploy/compose/opa/opa_config.yaml /config/opa_config.yaml
COPY deploy/compose/opa/start_opa.sh /start_opa.sh
ENTRYPOINT ["/start_opa.sh"]

FROM runtime AS bundle_builder
RUN apk add --no-cache openssl
COPY deploy/compose/opa/build_bundle.sh /build_bundle.sh
COPY deploy/compose/opa/bundle /policy_source
COPY deploy/compose/opa/signing_claims.json /config/signing_claims.json
ENTRYPOINT ["/build_bundle.sh"]
