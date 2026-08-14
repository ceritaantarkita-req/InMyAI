#!/usr/bin/env bash
set -euo pipefail

EXPECTED="${1:-}"
BASE="9abc3abba19ade6945c375f0fbe885cbefc686ff"
BRANCH="agent/v2x-phase5-manual-provider-selection-20260814"
CREATED_VENV_LINK=0

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

cleanup_expected_qa_artifacts_best_effort() {
  git restore --worktree --source=HEAD -- \
    apps/web/next-env.d.ts \
    apps/web/tsconfig.tsbuildinfo >/dev/null 2>&1 || true

  if [[ "$CREATED_VENV_LINK" == "1" && -L .venv ]]; then
    rm -f .venv || true
  fi
}

cleanup_expected_qa_artifacts_strict() {
  git restore --worktree --source=HEAD -- \
    apps/web/next-env.d.ts \
    apps/web/tsconfig.tsbuildinfo

  if [[ "$CREATED_VENV_LINK" == "1" ]]; then
    [[ -L .venv ]] || {
      echo "STOP: temporary .venv symlink was replaced or is missing" >&2
      return 1
    }
    rm -f .venv
  fi
}

# On any early failure, remove only the deterministic QA artifacts we created or
# allowlisted. Never run a broad git clean/reset here: unexpected source changes
# must remain visible for diagnosis.
trap 'rc=$?; cleanup_expected_qa_artifacts_best_effort; exit "$rc"' EXIT

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

# Keep the detached worktree self-contained for Node/Next/Turbopack. A symlink
# from this /tmp worktree to the source clone's node_modules crosses the Next
# project filesystem root and Turbopack rejects it. npm ci is lockfile-pinned,
# writes only local dependency state, and leaves product source untouched.
if [[ ! -d node_modules || -L node_modules ]]; then
  rm -rf node_modules
  echo "=== PREPARE WORKTREE NODE DEPENDENCIES ==="
  npm ci --no-audit --no-fund
fi

# Python dependencies may reuse the source clone's prepared virtualenv because
# Python does not impose Turbopack's project-root restriction. The symlink is a
# temporary QA artifact and is removed before the worktree is accepted as clean.
COMMON_DIR="$(git rev-parse --git-common-dir)"
if [[ "$COMMON_DIR" != /* ]]; then COMMON_DIR="$(pwd)/$COMMON_DIR"; fi
SOURCE_ROOT="$(cd "$(dirname "$COMMON_DIR")" && pwd)"

if [[ ! -e .venv ]]; then
  [[ -x "$SOURCE_ROOT/.venv/bin/python" ]] || {
    echo "STOP: source InMyAI .venv is missing; prepare the existing local QA environment in $SOURCE_ROOT first" >&2
    exit 1
  }
  ln -s "$SOURCE_ROOT/.venv" .venv
  CREATED_VENV_LINK=1
fi

echo "=== FULL INMYAI QA ==="
npm run qa

echo "=== PHASE 5 PROVIDER PORTABILITY REGRESSION ==="
.venv/bin/python -m pytest services/api/tests/test_provider_portability.py -q

echo "=== QA WORKTREE MUTATION CHECK ==="
POST_STATUS="$(git status --short)"
UNEXPECTED_MUTATION=0

if [[ -n "$POST_STATUS" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    case "$line" in
      " M apps/web/next-env.d.ts"|" M apps/web/tsconfig.tsbuildinfo")
        echo "EXPECTED QA-GENERATED MUTATION: $line"
        ;;
      "?? .venv")
        if [[ "$CREATED_VENV_LINK" == "1" && -L .venv ]]; then
          echo "EXPECTED QA-GENERATED MUTATION: $line"
        else
          echo "UNEXPECTED QA WORKTREE MUTATION: $line" >&2
          UNEXPECTED_MUTATION=1
        fi
        ;;
      *)
        echo "UNEXPECTED QA WORKTREE MUTATION: $line" >&2
        UNEXPECTED_MUTATION=1
        ;;
    esac
  done <<< "$POST_STATUS"
fi

[[ "$UNEXPECTED_MUTATION" == "0" ]] || {
  echo "STOP: QA changed worktree state outside the deterministic allowlist" >&2
  exit 1
}

echo "EXPECTED QA-GENERATED MUTATIONS: ALLOWLIST ONLY"
echo "=== CLEAN EXPECTED QA-GENERATED ARTIFACTS ==="
cleanup_expected_qa_artifacts_strict

FINAL_STATUS="$(git status --short)"
[[ -z "$FINAL_STATUS" ]] || {
  echo "STOP: QA worktree is still dirty after deterministic cleanup" >&2
  printf '%s\n' "$FINAL_STATUS" >&2
  exit 1
}

echo "QA WORKTREE FINAL STATUS: CLEAN"

# Successful explicit cleanup completed; disable the best-effort EXIT cleanup.
trap - EXIT

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
QA_WORKTREE_CLEANLINESS=PASS
PHASE 5: IN PROGRESS
========================================================
EOF
