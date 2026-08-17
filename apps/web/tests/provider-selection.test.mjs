import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const workspacePath = path.resolve(here, '..', 'src', 'components', 'Workspace.tsx')
const portablePagePath = path.resolve(here, '..', 'src', 'app', 'providers', 'page.tsx')

async function sources() {
  const [workspace, portablePage] = await Promise.all([
    readFile(workspacePath, 'utf8'),
    readFile(portablePagePath, 'utf8')
  ])
  return { workspace, portablePage }
}

test('chat provider selector now exposes the explicit, Hub-governed OpenRouter option (bridge/live-E2E closure checkpoint)', async () => {
  const { workspace } = await sources()
  assert.match(workspace, /<option value="auto">Automatic router<\/option>/)
  assert.match(workspace, /<option value="mock">Safe mock<\/option>/)
  assert.match(workspace, /<option value="ollama" disabled=\{!ollamaAvailable\}>Ollama local<\/option>/)
  assert.match(workspace, /<option value="openrouter" disabled=\{!openrouterReady\}>OpenRouter \(governed\)<\/option>/)
  assert.doesNotMatch(workspace, /<option value="openai"/)
})

test('chat composer only sends OpenRouter connection/model metadata that was already explicitly saved on /providers, never invents or defaults it', async () => {
  const { workspace } = await sources()
  // Disabled (and the send guard below) whenever either value is missing —
  // the composer never falls back to another provider or a default model.
  assert.match(workspace, /openrouterReady = Boolean\(openrouterConnectionId && openrouterModelId\)/)
  assert.match(workspace, /if \(provider === 'openrouter' && !openrouterReady\) return/)
  // Reads, never writes, the exact keys app/providers/page.tsx owns.
  assert.match(workspace, /window\.localStorage\.getItem\(OPENROUTER_CONNECTION_KEY\)/)
  assert.match(workspace, /window\.localStorage\.getItem\(OPENROUTER_MODEL_KEY\)/)
  assert.match(workspace, /const OPENROUTER_CONNECTION_KEY = 'inmyai:openrouter:connectionId'/)
  assert.match(workspace, /const OPENROUTER_MODEL_KEY = 'inmyai:openrouter:modelId'/)
  // The governed /api/chat request shape from services/api/app/schemas.py's
  // ChatRequest: connection_id + idempotency_key are only ever populated for
  // the explicit OpenRouter path, and a fresh idempotency key is minted per
  // send rather than reused.
  assert.match(workspace, /connection_id: provider === 'openrouter' \? openrouterConnectionId : undefined/)
  assert.match(workspace, /idempotency_key: provider === 'openrouter' \? newIdempotencyKey\('inmyai-chat'\) : undefined/)
  // Same credential-safety boundary already enforced on the /providers page:
  // the composer must never collect or reference a raw provider credential.
  assert.doesNotMatch(workspace, /type=["']password["']/i)
  assert.doesNotMatch(workspace, /OPENROUTER_API_KEY/)
  assert.doesNotMatch(workspace, /access[_-]?token/i)
  assert.doesNotMatch(workspace, /refresh[_-]?token/i)
  assert.doesNotMatch(workspace, /openrouter\.ai/i)
})

test('portable provider surface exposes the Hub-governed OpenRouter path', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /Hub-governed provider/)
  assert.match(portablePage, /OpenRouter connection/)
  assert.match(portablePage, /Credentials stay in InMyConnect/)
  assert.match(portablePage, /No automatic routing or silent fallback/)
  assert.match(portablePage, /SELECTED_GOVERNED_PATH/)
  assert.match(portablePage, /Every R1 chat still requires Hub authorization/)
})

test('OpenRouter model discovery is account-filtered through the InMyAI API and model choice stays explicit', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /\/api\/providers\/openrouter\/models/)
  assert.match(portablePage, /connection_id: connectionId\.trim\(\)/)
  assert.match(portablePage, /idempotency_key: newIdempotencyKey\('openrouter-models'\)/)
  assert.match(portablePage, /<option value="">Select a model explicitly<\/option>/)
  assert.match(portablePage, /No cloud model is selected or defaulted automatically/)
  assert.doesNotMatch(portablePage, /useState\(['"]gpt-/i)
})

test('portable provider UI stores only opaque connection/model metadata and cannot collect provider credentials', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /inmyai:openrouter:connectionId/)
  assert.match(portablePage, /inmyai:openrouter:modelId/)
  assert.match(portablePage, /placeholder="conn_…"/)
  assert.doesNotMatch(portablePage, /type=["']password["']/i)
  assert.doesNotMatch(portablePage, /OPENROUTER_API_KEY/)
  assert.doesNotMatch(portablePage, /access[_-]?token/i)
  assert.doesNotMatch(portablePage, /refresh[_-]?token/i)
  assert.doesNotMatch(portablePage, /openrouter\.ai/i)
})

test('portable provider selection remains manual and does not call chat as a side effect', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /\/api\/providers\/portable\/select/)
  assert.match(portablePage, /selection_mode: 'manual'/)
  assert.doesNotMatch(portablePage, /\/api\/chat/)
})
