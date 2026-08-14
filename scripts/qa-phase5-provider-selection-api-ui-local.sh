#!/usr/bin/env bash
set -euo pipefail

EXPECTED="${1:-}"
BASE="063a094b08bcbedaac0f59bb3c20952d0cd12be4"
BRANCH="agent/v2x-phase5-provider-selection-api-ui-20260814"
CREATED_VENV_LINK=0

if [[ ! "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: bash scripts/qa-phase5-provider-selection-api-ui-local.sh <expected-40-char-head>" >&2
  exit 2
fi

ACTUAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

cat <<EOF
=== PHASE 5 INMYAI PROVIDER SELECTION API/UI EXACT HEAD ===
base:     $BASE
expected: $EXPECTED
actual:   $ACTUAL
remote:   $REMOTE
EOF

[[ "$ACTUAL" == "$EXPECTED" ]] || { echo "STOP: detached worktree is not the expected head" >&2; exit 1; }
[[ "$REMOTE" == "$EXPECTED" ]] || { echo "STOP: remote Phase 5 API/UI branch changed" >&2; exit 1; }
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

trap 'rc=$?; cleanup_expected_qa_artifacts_best_effort; exit "$rc"' EXIT

echo "=== DIFF CHECK ==="
git diff --check "$BASE...$EXPECTED"

echo "=== PROVIDER SELECTION STATIC BOUNDARY ==="
python3 -m py_compile \
  services/api/app/provider_portability.py \
  services/api/app/main.py \
  services/api/tests/test_provider_portability.py \
  services/api/tests/test_provider_portability_api.py
python3 - <<'PY'
from pathlib import Path
from typing import get_args
from services.api.app.schemas import ChatRequest

main = Path('services/api/app/main.py').read_text(encoding='utf-8')
page = Path('apps/web/src/app/providers/page.tsx').read_text(encoding='utf-8')
workspace = Path('apps/web/src/components/Workspace.tsx').read_text(encoding='utf-8')

for required in (
    "@app.get('/api/providers/portable')",
    "@app.post('/api/providers/portable/select')",
    'list_portable_provider_catalog',
    'plan_manual_provider_selection',
):
    if required not in main:
        raise SystemExit(f'missing portable-provider API boundary: {required}')

if set(get_args(ChatRequest.model_fields['provider'].annotation)) != {'auto', 'mock', 'ollama'}:
    raise SystemExit('ChatRequest.provider execution boundary changed')

for required in (
    'Selection only',
    'Not connected for execution',
    'Credentials stay owned by InMyConnect',
    'No automatic routing',
    '/api/providers/portable/select',
):
    if required not in page:
        raise SystemExit(f'missing selection-only UI boundary: {required}')

for forbidden in ('/api/chat', 'api_key', 'access_token', 'refresh_token', 'type="password"'):
    if forbidden.lower() in page.lower():
        raise SystemExit(f'forbidden execution/secret primitive in portable-provider UI: {forbidden}')

for option in (
    '<option value="auto">Automatic router</option>',
    '<option value="mock">Safe mock</option>',
    '<option value="ollama" disabled={!ollamaAvailable}>Ollama local</option>',
):
    if option not in workspace:
        raise SystemExit(f'existing chat execution option changed: {option}')
if '<option value="openai"' in workspace:
    raise SystemExit('portable provider leaked into chat execution selector')

print('provider selection API/UI static boundary: PASS')
PY

echo "=== INMYAI HOSTED WORKFLOW BOUNDARY ==="
if grep -Eq '^[[:space:]]*(pull_request|push):' .github/workflows/ci.yml; then
  echo "STOP: hosted CI still has an automatic push/pull_request trigger" >&2
  exit 1
fi
if ! grep -Eq '^[[:space:]]*workflow_dispatch:' .github/workflows/ci.yml; then
  echo "STOP: hosted CI is not explicitly manual-only via workflow_dispatch" >&2
  exit 1
fi

echo "HOSTED PR WORKFLOW AUTO-TRIGGER: DISABLED"
echo "HOSTED PUSH WORKFLOW AUTO-TRIGGER: DISABLED"
echo "HOSTED WORKFLOW MANUAL DISPATCH: ENABLED"
echo "HOSTED ACTIONS ACCEPTANCE: NOT USED"
echo "HOSTED WORKFLOW TRIGGER BOUNDARY: PASS"

if [[ ! -d node_modules || -L node_modules ]]; then
  rm -rf node_modules
  echo "=== PREPARE WORKTREE NODE DEPENDENCIES ==="
  npm ci --no-audit --no-fund
fi

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

echo "=== FOCUSED PORTABLE PROVIDER API REGRESSION ==="
.venv/bin/python -m pytest \
  services/api/tests/test_provider_portability.py \
  services/api/tests/test_provider_portability_api.py -q

echo "=== FOCUSED PORTABLE PROVIDER WEB REGRESSION ==="
node --test apps/web/tests/provider-selection.test.mjs

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
trap - EXIT

cat <<EOF

========================================================
INMYAI PHASE 5 PROVIDER SELECTION API/UI CANDIDATE PASS
HEAD: $EXPECTED
BASE: $BASE
PORTABLE PROVIDER CATALOG API: EXPOSED
PORTABLE PROVIDER MANUAL PLAN API: EXPOSED
PORTABLE PROVIDER UI: SELECTION-ONLY
SELECTION STATUS: SELECTED_NOT_EXECUTABLE
CREDENTIAL RESOLUTION: INMYCONNECT_ONLY
RAW CREDENTIAL INPUT: NOT PRESENT
AUTOMATIC CLOUD ROUTING: NOT AUTHORIZED
PROVIDER DISPATCH: NOT AUTHORIZED
CHAT EXECUTION PROVIDERS: AUTO / MOCK / OLLAMA ONLY
HOSTED ACTIONS ACCEPTANCE: NOT USED
HOSTED_WORKFLOW_TRIGGER_BOUNDARY=PASS
LOCAL_WORKFLOW_EQUIVALENT_CI=PASS
QA_WORKTREE_CLEANLINESS=PASS
INMYAI PRODUCT PR: ELIGIBLE AFTER THIS CHECKPOINT
PHASE 5 API/UI CHECKPOINT: IN PROGRESS
========================================================
EOF
