#!/bin/sh
# SearXNG entrypoint wrapper — substitutes ${VAR} placeholders in
# settings.yml using environment variables before starting SearXNG.
#
# This lets the repo keep settings.yml with placeholder values
# (e.g. ${BRAVE_API_KEY}) while each deployment provides real
# values via .env or docker-compose environment.

SETTINGS_SRC="/etc/searxng/settings.yml"

if [ -f "$SETTINGS_SRC" ] && [ -n "$BRAVE_API_KEY" ]; then
    if grep -q '\${BRAVE_API_KEY}' "$SETTINGS_SRC" 2>/dev/null; then
        # sed -i creates temp files in the target dir which may not be
        # writable, so we copy to /tmp, edit there, then write back.
        TMPFILE="/tmp/searxng-settings.yml"
        cp "$SETTINGS_SRC" "$TMPFILE"
        sed -i "s|\${BRAVE_API_KEY}|${BRAVE_API_KEY}|g" "$TMPFILE"
        if cat "$TMPFILE" > "$SETTINGS_SRC" 2>/dev/null; then
            echo "entrypoint: BRAVE_API_KEY substituted in settings.yml"
        else
            # Fall back: write substituted settings to /tmp/ and tell SearXNG to read it
            cp "$TMPFILE" /tmp/searxng-settings-substituted.yml
            export SEARXNG_SETTINGS_PATH=/tmp/searxng-settings-substituted.yml
            echo "entrypoint: wrote substituted settings to SEARXNG_SETTINGS_PATH"
        fi
        rm -f "$TMPFILE"
    else
        echo "entrypoint: BRAVE_API_KEY already substituted, skipping"
    fi
fi

# Hand off to the normal SearXNG entrypoint
exec /usr/local/searxng/entrypoint.sh "$@"
