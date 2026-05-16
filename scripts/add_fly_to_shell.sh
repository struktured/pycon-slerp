#!/usr/bin/env bash
# Append the flyctl env to the user's shell rc (idempotently).
# Detects bash vs zsh; falls back to ~/.profile.
set -euo pipefail

case "${SHELL:-}" in
  */zsh) RC="$HOME/.zshrc" ;;
  */bash) RC="$HOME/.bashrc" ;;
  *) RC="$HOME/.profile" ;;
esac

MARKER="# >>> flyctl (pycon-slerp setup) >>>"
END="# <<< flyctl (pycon-slerp setup) <<<"

if grep -qF "$MARKER" "$RC" 2>/dev/null; then
  echo "Already present in $RC — nothing to do."
  exit 0
fi

{
  printf '\n%s\n' "$MARKER"
  echo 'export FLYCTL_INSTALL="$HOME/.fly"'
  echo 'export PATH="$FLYCTL_INSTALL/bin:$PATH"'
  printf '%s\n' "$END"
} >> "$RC"

echo "Appended flyctl env block to $RC"
echo "Open a new shell, or run:  source $RC"
