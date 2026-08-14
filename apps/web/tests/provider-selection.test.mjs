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

test('chat execution provider selector remains auto mock ollama only', async () => {
  const { workspace } = await sources()
  assert.match(workspace, /<option value="auto">Automatic router<\/option>/)
  assert.match(workspace, /<option value="mock">Safe mock<\/option>/)
  assert.match(workspace, /<option value="ollama" disabled=\{!ollamaAvailable\}>Ollama local<\/option>/)
  assert.doesNotMatch(workspace, /<option value="openai"/)
})

test('portable provider surface is explicitly selection-only and non-executable', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /Selection only/)
  assert.match(portablePage, /Not connected for execution/)
  assert.match(portablePage, /Credentials stay owned by InMyConnect/)
  assert.match(portablePage, /No automatic routing/)
  assert.match(portablePage, /SELECTED_NOT_EXECUTABLE/)
  assert.match(portablePage, /Provider dispatch is still disabled/)
})

test('portable provider model choice is explicit with no cloud default', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /const \[modelId, setModelId\] = useState\(''\)/)
  assert.match(portablePage, /placeholder="Enter a model ID explicitly"/)
  assert.match(portablePage, /No cloud model is selected or defaulted automatically/)
  assert.doesNotMatch(portablePage, /useState\(['"]gpt-/i)
})

test('portable provider UI cannot dispatch chat or collect raw credentials', async () => {
  const { portablePage } = await sources()
  assert.match(portablePage, /\/api\/providers\/portable\/select/)
  assert.doesNotMatch(portablePage, /\/api\/chat/)
  assert.doesNotMatch(portablePage, /provider\s*:\s*['"]openai['"]/)
  assert.doesNotMatch(portablePage, /type=["']password["']/i)
  assert.doesNotMatch(portablePage, /api[_-]?key/i)
  assert.doesNotMatch(portablePage, /access[_-]?token/i)
  assert.doesNotMatch(portablePage, /refresh[_-]?token/i)
})
