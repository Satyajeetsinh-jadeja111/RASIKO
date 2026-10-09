#!/bin/sh
# Reload renewed certificates without mounting the Docker socket into certbot.
set -eu
# Our shell command bypasses the image's nginx-only template hook.
envsubst '${DOMAIN}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
nginx -t
nginx -g 'daemon off;' &
server_pid=$!
trap 'kill -TERM "$server_pid"; exit 0' TERM INT
last=""
while kill -0 "$server_pid" 2>/dev/null; do
  current=$(cksum "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" 2>/dev/null || true)
  if [ -n "$last" ] && [ "$current" != "$last" ]; then
    nginx -t && nginx -s reload
  fi
  last="$current"
  sleep 60 &
  wait $! || true
done
wait "$server_pid"
