#!/usr/bin/env bash
set -euo pipefail

EXPECTED="${1:-}"
BASE="7cb6b3ea5ce49c164826f96971b116d93f85b493"
BRANCH="phase5-openrouter-inmyai-wiring-20260814"
CREATED_VENV_LINK=0

if [[ ! "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: bash scripts/qa-phase5-openrouter-inmyai-wiring-local.sh <expected-40-char-head>" >&2
  exit 2
fi

ACTUAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

cat <<EOF
=== INMYAI PHASE 5 OPENROUTER WIRING EXACT HEAD ===
base:     $BASE
expected: $EXPECTED
actual:   $ACTUAL
remote:   $REMOTE
EOF

[[ "$ACTUAL" == "$EXPECTED" ]] || { echo "STOP: detached worktree is not the expected head" >&2; exit 1; }
[[ "$REMOTE" == "$EXPECTED" ]] || { echo "STOP: remote InMyAI OpenRouter branch changed" >&2; exit 1; }
git cat-file -e "$BASE^{commit}"

PRE_STATUS="$(git status --short)"
[[ -z "$PRE_STATUS" ]] || { echo "STOP: QA worktree is dirty before testing" >&2; printf '%s\n' "$PRE_STATUS" >&2; exit 1; }

cleanup_expected_qa_artifacts_best_effort() {
  git restore --worktree --source=HEAD -- \
    apps/web/next-env.d.ts \
    apps/web/tsconfig.tsbuildinfo >/dev/null 2>&1 || true
  if [[ "$CREATED_VENV_LINK" == "1" && -L .venv ]]; then rm -f .venv || true; fi
}

cleanup_expected_qa_artifacts_strict() {
  git restore --worktree --source=HEAD -- \
    apps/web/next-env.d.ts \
    apps/web/tsconfig.tsbuildinfo
  if [[ "$CREATED_VENV_LINK" == "1" ]]; then
    [[ -L .venv ]] || { echo "STOP: temporary .venv symlink was replaced or is missing" >&2; return 1; }
    rm -f .venv
  fi
}

trap 'rc=$?; cleanup_expected_qa_artifacts_best_effort; exit "$rc"' EXIT

echo "=== DIFF CHECK ==="
git diff --check "$BASE...$EXPECTED"

EXPECTED_FILES="$(cat <<'EOF'
.env.example
apps/web/src/app/providers/page.tsx
apps/web/tests/provider-selection.test.mjs
docs/phase5-openrouter-inmyai-wiring-v1.md
scripts/qa-phase5-openrouter-inmyai-wiring-local.sh
services/api/app/config.py
services/api/app/connect_openrouter.py
services/api/app/main.py
services/api/app/provider_execution_contract.py
services/api/app/provider_portability.py
services/api/app/schemas.py
services/api/tests/test_connect_openrouter.py
services/api/tests/test_openrouter_governed_api.py
services/api/tests/test_provider_execution_contract.py
services/api/tests/test_provider_portability.py
services/api/tests/test_provider_portability_api.py
EOF
)"
ACTUAL_FILES="$(git diff --name-only "$BASE...$EXPECTED" | sort)"
[[ "$ACTUAL_FILES" == "$(printf '%s\n' "$EXPECTED_FILES" | sort)" ]] || {
  echo "STOP: checkpoint diff is outside the exact file allowlist" >&2
  echo "=== EXPECTED ===" >&2
  printf '%s\n' "$EXPECTED_FILES" >&2
  echo "=== ACTUAL ===" >&2
  printf '%s\n' "$ACTUAL_FILES" >&2
  exit 1
}

echo "=== OPENROUTER INMYAI STATIC BOUNDARY ==="
python3 -m py_compile \
  services/api/app/config.py \
  services/api/app/connect_openrouter.py \
  services/api/app/main.py \
  services/api/app/provider_portability.py \
  services/api/app/provider_execution_contract.py \
  services/api/app/schemas.py \
  services/api/tests/test_connect_openrouter.py \
  services/api/tests/test_openrouter_governed_api.py \
  services/api/tests/test_provider_portability.py \
  services/api/tests/test_provider_portability_api.py \
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
    HUB_R1_SERVICE_IDENTITY,
    plan_governed_provider_execution,
)
from services.api.app.provider_portability import list_portable_provider_catalog

assert HUB_GOVERNANCE_REF == 'dbfbb3d3fa1c6e5ff217814e8bfbb8ef5c5cc1b7'
assert CONNECT_GOVERNED_REF == '65d8be8692da237961dc19a76147bab8739c8597'
assert HUB_EXECUTION_ENABLED is True
assert HUB_R1_DECISION == 'execute'
assert HUB_R1_SERVICE_IDENTITY == 'agent:inmyai'
assert HUB_AGENT_ALLOWED_SUBJECT_MODES == ('mutate',)
assert CONNECT_ACTION_MODES == ('read', 'model-api')
assert CONNECT_RISK_CLASSES == ('R0', 'R1')

catalog = list_portable_provider_catalog()
assert len(catalog) == 1
provider = catalog[0]
assert provider['provider_id'] == 'openrouter'
assert provider['execution_state'] == 'hub-governed'
assert provider['selection_mode'] == 'manual-only'
assert provider['automatic_routing_allowed'] is False
assert provider['dispatch_allowed'] is True
assert provider['credential_resolution'] == 'INMYCONNECT_ONLY'
assert provider['default_model'] is None

plan = plan_governed_provider_execution({
    'provider_id': 'openrouter',
    'model_id': 'qwen/qwen3-coder',
    'data_sensitivity': 'INTERNAL',
    'input_bytes': 1024,
    'requested_output_tokens': 512,
    'idempotency_key': 'qa-openrouter-0001',
    'input_digest': 'sha256:' + ('a' * 64),
    'connection_id': 'conn_' + ('a' * 16),
})
assert plan['execution_status'] == 'GOVERNED_EXECUTION_READY'
assert plan['readiness'] == 'READY_FOR_CONNECT_HTTP_RUNTIME'
assert plan['blockers'] == []
assert plan['network_call_performed'] is False
assert plan['provider_dispatch_performed'] is False
assert plan['automatic_routing_allowed'] is False
assert plan['silent_fallback_allowed'] is False

runtime_sources = '\n'.join(
    Path(path).read_text(encoding='utf-8').lower()
    for path in (
        'services/api/app/connect_openrouter.py',
        'services/api/app/main.py',
    )
)
for forbidden in (
    'https://openrouter.ai',
    'api.openai.com',
    'openrouter_api_key',
    'openai_api_key',
):
    if forbidden in runtime_sources:
        raise SystemExit(f'forbidden direct provider primitive in InMyAI runtime: {forbidden}')

client_source = Path('services/api/app/connect_openrouter.py').read_text(encoding='utf-8')
for required in (
    "ipaddress.ip_address",
    "address.is_loopback",
    "follow_redirects=False",
    "'/api/openrouter/models'",
    "'/api/openrouter/chat'",
):
    if required not in client_source:
        raise SystemExit(f'missing Connect loopback boundary: {required}')

main_source = Path('services/api/app/main.py').read_text(encoding='utf-8')
for required in (
    "provider='openrouter'",
    "without fallback",
    "'/api/providers/openrouter/models'",
):
    if required not in main_source:
        raise SystemExit(f'missing OpenRouter governed runtime boundary: {required}')

schemas_source = Path('services/api/app/schemas.py').read_text(encoding='utf-8')
tree = ast.parse(schemas_source)
chat_request = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ChatRequest'), None)
if chat_request is None:
    raise SystemExit('ChatRequest schema is missing')
provider_annotation = None
field_names = set()
for statement in chat_request.body:
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        field_names.add(statement.target.id)
        if statement.target.id == 'provider':
            provider_annotation = statement.annotation
if not (
    isinstance(provider_annotation, ast.Subscript)
    and isinstance(provider_annotation.value, ast.Name)
    and provider_annotation.value.id == 'Literal'
):
    raise SystemExit('ChatRequest.provider is no longer a Literal boundary')
provider_slice = provider_annotation.slice
provider_nodes = provider_slice.elts if isinstance(provider_slice, ast.Tuple) else [provider_slice]
provider_values = {
    node.value for node in provider_nodes
    if isinstance(node, ast.Constant) and isinstance(node.value, str)
}
if provider_values != {'auto', 'mock', 'ollama', 'openrouter'}:
    raise SystemExit(f'ChatRequest.provider boundary unexpected: {provider_values}')
for forbidden_field in ('api_key', 'openrouter_api_key', 'access_token', 'refresh_token', 'password', 'credential'):
    if forbidden_field in field_names:
        raise SystemExit(f'raw provider credential field entered ChatRequest: {forbidden_field}')

example = Path('.env.example').read_text(encoding='utf-8')
for forbidden_definition in ('OPENROUTER_API_KEY=', 'OPENAI_API_KEY='):
    if forbidden_definition in example:
        raise SystemExit(f'provider API key must not be configured in InMyAI: {forbidden_definition}')
assert 'INMYAI_CONNECT_BASE_URL=http://127.0.0.1:8766' in example
assert 'INMYAI_HUB_SERVICE_TOKEN=' in example

web_source = Path('apps/web/src/app/providers/page.tsx').read_text(encoding='utf-8').lower()
for forbidden in ('openrouter.ai', 'type="password"', 'openrouter_api_key', 'access_token', 'refresh_token'):
    if forbidden in web_source:
        raise SystemExit(f'provider credential/direct endpoint leaked into web UI: {forbidden}')

print('OpenRouter InMyAI static boundary: PASS')
PY

echo "=== HOSTED WORKFLOW BOUNDARY ==="
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

echo "=== FOCUSED OPENROUTER API REGRESSION ==="
.venv/bin/python -m pytest \
  services/api/tests/test_connect_openrouter.py \
  services/api/tests/test_openrouter_governed_api.py \
  services/api/tests/test_provider_portability.py \
  services/api/tests/test_provider_portability_api.py \
  services/api/tests/test_provider_execution_contract.py -q

echo "=== FOCUSED OPENROUTER WEB REGRESSION ==="
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
[[ "$UNEXPECTED_MUTATION" == "0" ]] || { echo "STOP: QA changed worktree state outside the deterministic allowlist" >&2; exit 1; }

echo "EXPECTED QA-GENERATED MUTATIONS: ALLOWLIST ONLY"
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
INMYAI PHASE 5 OPENROUTER WIRING CANDIDATE PASS
HEAD: $EXPECTED
BASE: $BASE
PORTABLE PROVIDER: OPENROUTER ONLY
HUB GOVERNANCE REF: dbfbb3d3fa1c6e5ff217814e8bfbb8ef5c5cc1b7
CONNECT GOVERNED REF: 65d8be8692da237961dc19a76147bab8739c8597
MODEL DISCOVERY UI: ACCOUNT-FILTERED VIA CONNECT CONTRACT
CLOUD MODEL DEFAULT: NONE
MODEL SELECTION: EXPLICIT / MANUAL ONLY
INMYAI DIRECT PROVIDER NETWORK: NOT PRESENT
OPENROUTER API KEY IN INMYAI: NOT PRESENT
BROWSER PROVIDER CREDENTIAL INPUT: NOT PRESENT
HUB SERVICE IDENTITY: SERVER-SIDE ONLY
CONNECT BASE URL: EXPLICIT LOOPBACK IP ONLY
OPENROUTER CHAT API CONTRACT: HUB-GOVERNED
OPENROUTER FAILURE MOCK FALLBACK: DISABLED
AUTOMATIC CLOUD ROUTING: DISABLED
SILENT FALLBACK: DISABLED
CONNECT HTTP BRIDGE IMPLEMENTATION: REMAINING NEXT CHECKPOINT
NORMAL QA LIVE CREDIT SPEND: NONE
HOSTED ACTIONS ACCEPTANCE: NOT USED
LOCAL_QA=PASS
QA_WORKTREE_CLEANLINESS=PASS
========================================================
EOF
