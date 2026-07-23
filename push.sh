#!/usr/bin/env bash
# push.sh — create the repo on GitHub and push. Run with:  bash push.sh
set -euo pipefail

REPO="acceptance-traceability-gate"
OWNER="SINGHL25"

cd "$(dirname "$0")"

echo "==> source policy gate"
bash scripts/check-sources.sh

echo "==> tests"
python3 -m pytest -q

echo "==> git init"
git init -q
git branch -M main
git add -A
git commit -q -m "acceptance traceability gate: phase chain, defect ageing, sign-off, evidence pack"

echo "==> create + push"
gh repo create "$REPO" --public --source=. --remote=origin --push

echo "==> topics + description"
gh repo edit "$OWNER/$REPO" \
  --description "Requirements traceability and phase-gate acceptance for field-deployed ITS systems" \
  --add-topic its-tolling \
  --add-topic portfolio \
  --add-topic systems-engineering \
  --add-topic python

echo ""
echo "Done: https://github.com/$OWNER/$REPO"
echo "Next: https://share.streamlit.io  ->  New app  ->  $OWNER/$REPO  ->  app.py"
