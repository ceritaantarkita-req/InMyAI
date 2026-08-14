#!/usr/bin/env bash
set -euo pipefail

EXPECTED="${1:-}"
BASE="9abc3abba19ade6945c375f0fbe885cbefc686ff"
BRANCH="agent/v2x-phase5-manual-provider-selection-20260814"

if [[ ! "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: bash scripts/qa-phase5-manual-provider-selection-local.sh <expected-40-char-head>" >&2
  exit 2
fi

ACTUAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

cat <<EOF
=== PHASE 5 INMYAI MANUAL PROVIDER SELECTION EXACT HEAD ===
base:     $BASE
expected: $EXPECTED
actual:   $ACTUAL
remote:   $REMOTE
EOF

[[ "$ACTUAL" == "$EXPECTED" ]] || { echo "STOP: detached worktree is not the expected head" >&2; exit 1; }
[[ "$REMOTE" == "$EXPECTED" ]] || { echo "STOP: remote Phase 5 InMyAI branch changed" >&2; exit 1; }
git cat-file -e "$BASE^{commit}"

PRE_STATUS="$(git status --short)"
[[ -z "$PRE_STATUS" ]] || { echo "STOP: QA worktree is dirty before testing" >&2; printf '%s\n' "$PRE_STATUS" >&2; exit 1; }

echo "=== DIFF CHECK ==="
git diff --check "$BASE...$EXPECTED"

echo "=== PYTHON STATIC / CANDIDATE TEST ==="
python3 -m py_compile services/api/app/provider_portability.py services/api/tests/test_provider_portability.py
python3 - <<'PY'
from pathlib import Path
source = Path('services/api/app/provider_portability.py').read_text(encoding='utf-8').lower()
for token in (
    'httpx', 'requests', 'urllib.request', 'socket.', 'subprocess',
    'openai_api_key', 'authorization:', 'os.environ', 'getenv(',
):
    if token in source:
        raise SystemExit(f'forbidden provider execution/secret primitive found: {token}')
print('provider portability static boundary: PASS')
PY

echo "=== INMYAI HOSTED WORKFLOW BOUNDARY ==="
if grep -Eq 'runs-on:[[:space:]]*ubuntu-latest' .github/workflows/ci.yml && grep -Eq '^[[:space:]]*pull_request:' .github/workflows/ci.yml; then
  echo "HOSTED PR WORKFLOW PRESENT: YES"
  echo "HOSTED ACTIONS ACCEPTANCE: NOT USED"
  echo "INMYAI PR OPENING: BLOCKED UNTIL WORKFLOW/TRIGGER BOUNDARY IS RECONCILED"
else
  echo "HOSTED PR WORKFLOW PRESENT: NO/CHANGED — review exact workflow before any PR"
fi

# The repository QA script expects product-local dependency paths. In a detached
# git worktree, reuse the already-installed dependencies from the source clone
# without copying secrets or changing tracked files.
COMMON_DIR="$(git rev-parse --git-common-dir)"
if [[ "$COMMON_DIR" != /* ]]; then COMMON_DIR="$(pwd)/$COMMON_DIR"; fi
SOURCE_ROOT="$(cd "$(dirname "$COMMON_DIR")" && pwd)"

if [[ ! -e node_modules ]]; then
  [[ -d "$SOURCE_ROOT/node_modules" ]] || {
    echo "STOP: source InMyAI node_modules is missing; run npm ci in $SOURCE_ROOT first" >&2
    exit 1
  }
  ln -s "$SOURCE_ROOT/node_modules" node_modules
fi

if [[ ! -e .venv ]]; then
  [[ -x "$SOURCE_ROOT/.venv/bin/python" ]] || {
    echo "STOP: source InMyAI .venv is missing; prepare the existing local QA environment in $SOURCE_ROOT first" >&2
    exit 1
  }
  ln -s "$SOURCE_ROOT/.venv" .venv
fi

echo "=== FULL INMYAI QA ==="
npm run qa

echo "=== PHASE 5 PROVIDER PORTABILITY REGRESSION ==="
.venv/bin/python -m pytest services/api/tests/test_provider_portability.py -q

POST_STATUS="$(git status --short)"
[[ -z "$POST_STATUS" ]] || {
  echo "STOP: QA changed tracked worktree state" >&2
  printf '%s\n' "$POST_STATUS" >&2
  exit 1
}

cat <<EOF

========================================================
INMYAI PHASE 5 MANUAL PROVIDER SELECTION FOUNDATION CANDIDATE PASS
HEAD: $EXPECTED
BASE: $BASE
UPSTREAM CONNECT FOUNDATION: ef39c199c302f3e6797994e0fa4a025d2a47b241
PORTABLE PROVIDER: OPENAI OFFICIAL API DESCRIPTOR
SELECTION MODE: MANUAL-ONLY
SELECTION STATUS: SELECTED_NOT_EXECUTABLE
CREDENTIAL RESOLUTION: INMYCONNECT_ONLY
RAW CREDENTIAL EXPOSURE: NOT AUTHORIZED
BROWSER/SESSION CREDENTIALS: NOT AUTHORIZED
AUTOMATIC CLOUD ROUTING: NOT AUTHORIZED
PROVIDER DISPATCH: NOT IMPLEMENTED / NOT AUTHORIZED
CURRENT OLLAMA/MOCK CHAT PATH: UNCHANGED
HOSTED ACTIONS ACCEPTANCE: NOT USED
INMYAI PRODUCT PR: NOT AUTHORIZED BY THIS CHECKPOINT
LOCAL_WORKFLOW_EQUIVALENT_CI=PASS
PHASE 5: IN PROGRESS
========================================================
EOF
