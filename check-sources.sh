#!/usr/bin/env bash
# Fails if any blocked identifier appears in the tree.
# Run: bash scripts/check-sources.sh
set -uo pipefail

BLOCKED=(
  "kapsch" "connecteast" "transurban" "linkt"
  "west gate" "wgtp" "mlff-g3" "ceips" "itamp"
  "tomo" "srts" "macfe"
  "10\.[0-9]\+\.[0-9]\+\.[0-9]\+" "192\.168\." "172\.1[6-9]\."
  "password[[:space:]]*[:=]" "api[_-]\?key[[:space:]]*[:=]"
  "BEGIN [A-Z ]*PRIVATE KEY"
)

FAIL=0
for pat in "${BLOCKED[@]}"; do
  if grep -rniI --exclude-dir=.git --exclude-dir=.venv \
       --exclude="check-sources.sh" --exclude="SOURCE-POLICY.md" \
       -e "$pat" . >/dev/null 2>&1; then
    echo "BLOCKED identifier found: $pat"
    FAIL=1
  fi
done

if [ "$FAIL" -eq 0 ]; then echo "check-sources: clean"; else echo "check-sources: FAILED"; fi
exit "$FAIL"
