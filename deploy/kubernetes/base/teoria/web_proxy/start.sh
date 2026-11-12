set -eu
TEORIA_DNS_RESOLVER=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf)
case "$TEORIA_DNS_RESOLVER" in *:*) TEORIA_DNS_RESOLVER="[$TEORIA_DNS_RESOLVER]";; esac
export TEORIA_DNS_RESOLVER
: "${TEORIA_CLUSTER_DOMAIN:=cluster.local}"
export TEORIA_CLUSTER_DOMAIN
envsubst '${TEORIA_DNS_RESOLVER} ${TEORIA_CLUSTER_DOMAIN}' < /etc/teoria_proxy/default.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
