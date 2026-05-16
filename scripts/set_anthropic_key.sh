#!/usr/bin/env bash
# Set the ANTHROPIC_API_KEY as a Fly secret (encrypted at rest, never in image).
# Triggers a rolling restart so the new value is live.
#
# Pulls the key from $ANTHROPIC_API_KEY, then ~/.anthropic-key, then prompts.
# The key is NEVER written to disk by this script.
set -euo pipefail
export PATH="$HOME/.fly/bin:$PATH"

APP="${FLY_APP:-pycon-slerp}"

KEY="${ANTHROPIC_API_KEY:-}"
if [[ -z "$KEY" && -f "$HOME/.anthropic-key" ]]; then
  KEY="$(< "$HOME/.anthropic-key")"
fi
if [[ -z "$KEY" ]]; then
  read -rsp "ANTHROPIC_API_KEY: " KEY; echo
fi
if [[ -z "$KEY" ]]; then
  echo "no key provided" >&2; exit 1
fi
if [[ ! "$KEY" =~ ^sk-ant- ]]; then
  echo "warning: key doesn't look like an Anthropic key (sk-ant-…)" >&2
fi

fly secrets set ANTHROPIC_API_KEY="$KEY" -a "$APP"

unset KEY

echo
echo "Done. Machine is restarting — give it 10–20 seconds, then:"
echo "  curl https://${APP}.fly.dev/api/health"
echo "should show anthropic_key_set: true"
