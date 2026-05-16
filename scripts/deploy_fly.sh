#!/usr/bin/env bash
# Deploy pycon-slerp to Fly.io.
#
# Idempotent: re-running will skip steps that are already done (launch, volume,
# existing secrets). Set the env vars below before running, or be prompted.
#
# Required in the environment:
#   SERPAPI_API_KEY   — your SerpApi key (will be a Fly secret, never in image)
#
# Optional:
#   FLY_APP           — override app name (default: read from fly.toml)
#   FLY_REGION        — override region   (default: read from fly.toml)
#   ADMIN_TOKEN       — pre-set token; otherwise we generate one
set -euo pipefail

export PATH="$HOME/.fly/bin:$PATH"

# --- preflight ----------------------------------------------------------------
if ! command -v fly >/dev/null 2>&1; then
  echo "fly CLI not found. Run scripts/setup_fly.sh first." >&2
  exit 1
fi

if ! fly auth whoami >/dev/null 2>&1; then
  echo "fly not logged in. Run: fly auth login" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f fly.toml ]]; then
  echo "fly.toml missing — are you in the repo root?" >&2
  exit 1
fi

APP="${FLY_APP:-$(awk -F'"' '/^app[[:space:]]*=/{print $2; exit}' fly.toml)}"
REGION="${FLY_REGION:-$(awk -F'"' '/^primary_region/{print $2; exit}' fly.toml)}"
echo "App:    $APP"
echo "Region: $REGION"

# --- secrets we need ----------------------------------------------------------
if [[ -z "${SERPAPI_API_KEY:-}" ]]; then
  # Try .env as a convenience
  if [[ -f .env ]] && grep -q '^SERPAPI_API_KEY=' .env; then
    SERPAPI_API_KEY="$(grep '^SERPAPI_API_KEY=' .env | head -1 | cut -d= -f2-)"
  fi
fi
if [[ -z "${SERPAPI_API_KEY:-}" ]]; then
  read -rsp "SERPAPI_API_KEY: " SERPAPI_API_KEY; echo
fi
if [[ -z "$SERPAPI_API_KEY" ]]; then
  echo "SERPAPI_API_KEY is required." >&2
  exit 1
fi

ADMIN_TOKEN="${ADMIN_TOKEN:-$(openssl rand -hex 16)}"

# --- 1. launch app if it doesn't exist ----------------------------------------
if fly apps list --json 2>/dev/null | grep -q "\"Name\":[[:space:]]*\"$APP\""; then
  echo "✓ app '$APP' already exists"
else
  echo "→ creating app '$APP' (no deploy yet)"
  fly launch --no-deploy --copy-config --yes --name "$APP" --region "$REGION"
fi

# --- 2. create the persistent volume ------------------------------------------
if fly volumes list -a "$APP" 2>/dev/null | grep -q pycon_data; then
  echo "✓ volume 'pycon_data' already exists"
else
  echo "→ creating volume 'pycon_data' (1 GB in $REGION)"
  fly volume create pycon_data --region "$REGION" --size 1 --yes -a "$APP"
fi

# --- 3. set secrets (only updates if changed) ---------------------------------
echo "→ setting secrets"
fly secrets set \
  SERPAPI_API_KEY="$SERPAPI_API_KEY" \
  ADMIN_TOKEN="$ADMIN_TOKEN" \
  -a "$APP" \
  --stage    # stage; the deploy below will release them in one go

# --- 4. deploy ----------------------------------------------------------------
echo "→ deploying"
fly deploy -a "$APP"

# --- 5. report ----------------------------------------------------------------
HOST="$(fly status -a "$APP" --json | python3 -c 'import sys,json; print(json.load(sys.stdin)["Hostname"])')"
echo
echo "============================================================"
echo "  Deployed: https://$HOST/"
echo "  Share:    https://$HOST/?t=$ADMIN_TOKEN"
echo "============================================================"
echo
echo "The ?t= URL unlocks Ask + Ingest for the recipient. The plain URL"
echo "is read-only (browse the pre-seeded graph + WebLLM ingest only)."
echo
echo "Token saved to .fly-admin-token (gitignored). Keep this — anyone with"
echo "it can spend your SerpApi quota."
printf '%s\n' "$ADMIN_TOKEN" > .fly-admin-token
chmod 600 .fly-admin-token
