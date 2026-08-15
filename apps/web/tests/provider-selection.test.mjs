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

test('legacy chat provider selector remains local until the explicit OpenRouter UI handoff is completed', async () => {
  const { workspace } = await sources()
  assert.match(workspace, /<option value="auto">Automatic router<\/option>/)
  assert.match(workspace, /<option value="mock">Safe mock<\/option>/)
  assert.match(workspace, /<option value="ollama" disabled=\{!ollamaAvailable\}>Ollama local<\/option>/)
  assert.doesNotMatch(workspace, /<option value="openai"/)
  assert.doesNotMatch(workspace, /<option value="openrouter"/)
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
