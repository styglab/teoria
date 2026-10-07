#!/bin/sh
set -eu

chown -R opa:opa /var/lib/opa
exec su-exec opa:opa /opa "$@"
