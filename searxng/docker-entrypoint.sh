#!/bin/sh
# SearXNG entrypoint wrapper — substitutes ${VAR} placeholders in
# settings.yml using environment variables before starting SearXNG.
#
# This lets the repo keep settings.yml with placeholder values
# (e.g. ${BRAVE_API_KEY}) while each deployment provides real
# values via .env or docker-compose environment.

set -e

SETTINGS_SRC="/etc/searxng/settings.yml"

if [ -f "$SETTINGS_SRC" ] && [ -n "$BRAVE_API_KEY" ]; then
    # sed -i creates temp files in the target dir which may not be
    # writable, so we copy to /tmp, edit there, then write back.
    TMPFILE="/tmp/searxng-settings.yml"
    cp "$SETTINGS_SRC" "$TMPFILE"
    sed -i "s|\${BRAVE_API_KEY}|${BRAVE_API_KEY}|g" "$TMPFILE"
    cat "$TMPFILE" > "$SETTINGS_SRC"
    rm -f "$TMPFILE"
    echo "entrypoint: BRAVE_API_KEY substituted in settings.yml"
fi

# Hand off to the normal SearXNG entrypoint
exec /usr/local/searxng/entrypoint.sh "$@"
