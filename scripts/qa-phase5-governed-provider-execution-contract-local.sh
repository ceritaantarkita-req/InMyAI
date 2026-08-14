#!/usr/bin/env bash
set -euo pipefail

EXPECTED="${1:-}"
BASE="51280527dda74fa2292d16a2824b355fc6220367"
BRANCH="agent/phase5-governed-provider-execution-contract-20260814"
CREATED_VENV_LINK=0

if [[ ! "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: bash scripts/qa-phase5-governed-provider-execution-contract-local.sh <expected-40-char-head>" >&2
  exit 2
fi

ACTUAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

cat <<EOF
=== PHASE 5 INMYAI GOVERNED PROVIDER EXECUTION CONTRACT EXACT HEAD ===
base:     $BASE
expected: $EXPECTED
actual:   $ACTUAL
remote:   $REMOTE
EOF

[[ "$ACTUAL" == "$EXPECTED" ]] || { echo "STOP: detached worktree is not the expected head" >&2; exit 1; }
[[ "$REMOTE" == "$EXPECTED" ]] || { echo "STOP: remote governed execution contract branch changed" >&2; exit 1; }
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

echo "=== GOVERNED EXECUTION CONTRACT STATIC BOUNDARY ==="
python3 -m py_compile \
  services/api/app/provider_portability.py \
  services/api/app/provider_execution_contract.py \
  services/api/tests/test_provider_portability.py \
  services/api/tests/test_provider_execution_contract.py

python3 - <<'PY'
import ast
from pathlib import Path

from services.api.app.provider_execution_contract import (
    CONNECT_ACTION_MODES,
    CONNECT_GOVERNED_REF,
    CONNECT_RISK_CLASSES,
    HUB_AGENT_ALLOWED_SUBJECT_MODES,
    HUB_EXECUTION_ENABLED,
    HUB_GOVERNANCE_REF,
    HUB_R1_DECISION,
    plan_governed_provider_execution,
)

assert HUB_GOVERNANCE_REF == 'cb660413941075337bd14aafedc79f998e01727a'
assert CONNECT_GOVERNED_REF == '08b381203e8a3b7c379a1b7da3683a286b91d9f7'
assert HUB_EXECUTION_ENABLED is False
assert HUB_R1_DECISION == 'plan-only'
assert HUB_AGENT_ALLOWED_SUBJECT_MODES == ('mutate',)
assert CONNECT_ACTION_MODES == ('read',)
assert CONNECT_RISK_CLASSES == ('R0',)

plan = plan_governed_provider_execution({
    'provider_id': 'openai',
    'model_id': 'qa-model-id',
    'data_sensitivity': 'INTERNAL',
    'input_bytes': 1024,
    'requested_output_tokens': 512,
    'idempotency_key': 'qa-contract-0001',
    'input_digest': 'sha256:' + ('a' * 64),
})
assert plan['execution_status'] == 'EXECUTION_NOT_AUTHORIZED'
assert plan['readiness'] == 'BLOCKED_UPSTREAM_CAPABILITY_GAP'
assert plan['network_call_performed'] is False
assert plan['provider_dispatch_performed'] is False
assert plan['credential_resolution_performed'] is False
assert plan['hub_authorization_performed'] is False
assert plan['automatic_routing_allowed'] is False
assert plan['silent_fallback_allowed'] is False
assert plan['fallback_performed'] is False

codes = {item['code'] for item in plan['blockers']}
required_codes = {
    'PROVIDER_DESCRIPTOR_CONTRACT_ONLY',
    'HUB_EXECUTION_DISABLED',
    'HUB_R1_PLAN_ONLY',
    'HUB_AGENT_EXECUTE_DELEGATION_UNAVAILABLE',
    'CONNECT_R1_MODEL_EXECUTOR_UNAVAILABLE',
    'CONNECT_CONNECTION_NOT_BOUND',
}
assert required_codes <= codes

source = Path('services/api/app/provider_execution_contract.py').read_text(encoding='utf-8').lower()
for forbidden in (
    'httpx', 'requests', 'urllib.request', 'socket.', 'subprocess',
    'api.openai.com', '/responses', 'authorization:', 'os.environ', 'getenv(',
):
    if forbidden in source:
        raise SystemExit(f'forbidden network/provider primitive in execution contract: {forbidden}')

schemas_source = Path('services/api/app/schemas.py').read_text(encoding='utf-8')
tree = ast.parse(schemas_source)
chat_request = next(
    (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ChatRequest'),
    None,
)
if chat_request is None:
    raise SystemExit('ChatRequest schema is missing')
provider_annotation = None
for statement in chat_request.body:
    if (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == 'provider'
    ):
        provider_annotation = statement.annotation
        break
if not (
    isinstance(provider_annotation, ast.Subscript)
    and isinstance(provider_annotation.value, ast.Name)
    and provider_annotation.value.id == 'Literal'
):
    raise SystemExit('ChatRequest.provider is no longer a Literal boundary')
provider_slice = provider_annotation.slice
provider_nodes = provider_slice.elts if isinstance(provider_slice, ast.Tuple) else [provider_slice]
provider_values = {
    node.value
    for node in provider_nodes
    if isinstance(node, ast.Constant) and isinstance(node.value, str)
}
if provider_values != {'auto', 'mock', 'ollama'} or len(provider_nodes) != 3:
    raise SystemExit('ChatRequest.provider execution boundary changed')

print('governed provider execution contract static boundary: PASS')
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

echo "=== FOCUSED GOVERNED PROVIDER EXECUTION CONTRACT REGRESSION ==="
.venv/bin/python -m pytest \
  services/api/tests/test_provider_portability.py \
  services/api/tests/test_provider_portability_api.py \
  services/api/tests/test_provider_execution_contract.py -q

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
INMYAI PHASE 5 GOVERNED PROVIDER EXECUTION CONTRACT CANDIDATE PASS
HEAD: $EXPECTED
BASE: $BASE
HUB GOVERNANCE REF: cb660413941075337bd14aafedc79f998e01727a
CONNECT GOVERNED REF: 08b381203e8a3b7c379a1b7da3683a286b91d9f7
PORTABLE PROVIDER: OPENAI / R1 / CONTRACT-ONLY
EXECUTION STATUS: EXECUTION_NOT_AUTHORIZED
READINESS: BLOCKED_UPSTREAM_CAPABILITY_GAP
HUB EXECUTION: DISABLED
HUB R1: PLAN-ONLY
HUB AGENT EXECUTE DELEGATION: NOT AVAILABLE
CONNECT EXECUTION FOUNDATION: READ / R0 ONLY
CONNECT R1 MODEL EXECUTOR: NOT AVAILABLE
CREDENTIAL RESOLUTION: INMYCONNECT ONLY / NOT PERFORMED
RAW CREDENTIAL INPUT: REJECTED
RAW PROMPT/CONTENT INPUT TO PLANNER: REJECTED
AUTOMATIC CLOUD ROUTING: NOT AUTHORIZED
SILENT FALLBACK: NOT AUTHORIZED
PROVIDER DISPATCH: NOT AUTHORIZED / NOT PERFORMED
CURRENT CHAT EXECUTION PROVIDERS: AUTO / MOCK / OLLAMA ONLY
HOSTED ACTIONS ACCEPTANCE: NOT USED
HOSTED_WORKFLOW_TRIGGER_BOUNDARY=PASS
LOCAL_WORKFLOW_EQUIVALENT_CI=PASS
QA_WORKTREE_CLEANLINESS=PASS
INMYAI PRODUCT PR: ELIGIBLE AFTER THIS CHECKPOINT
PHASE 5 GOVERNED EXECUTION CONTRACT: IN PROGRESS
========================================================
EOF
