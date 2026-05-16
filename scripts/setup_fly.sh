#!/usr/bin/env bash
# Step 1 of the Fly.io deploy: install the flyctl CLI if missing, then verify.
# Idempotent — safe to re-run.
set -euo pipefail

FLYCTL_INSTALL="${FLYCTL_INSTALL:-$HOME/.fly}"
export FLYCTL_INSTALL
export PATH="$FLYCTL_INSTALL/bin:$PATH"

if command -v fly >/dev/null 2>&1; then
  echo "fly already installed at $(command -v fly)"
else
  echo "Installing flyctl into $FLYCTL_INSTALL ..."
  curl -L https://fly.io/install.sh | sh
fi

echo
fly version

cat <<EOF

Next:
  1. Add these to your shell rc (~/.bashrc or ~/.zshrc) so future shells see fly:
       export FLYCTL_INSTALL="$FLYCTL_INSTALL"
       export PATH="\$FLYCTL_INSTALL/bin:\$PATH"

  2. Log in (opens a browser):
       fly auth login

  3. Then run scripts/deploy_fly.sh
EOF
