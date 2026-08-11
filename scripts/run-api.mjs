import { spawn } from 'node:child_process'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { consumeLifecycleEnvironment } from './lifecycle-environment.mjs'
import { assertLoopbackPortAvailable, resolveInMyAIPorts } from './ports.mjs'
import { stopChildTree } from './process-tree.mjs'

const { api } = resolveInMyAIPorts()
await assertLoopbackPortAvailable('INMYAI_API_PORT', api)
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = process.platform === 'win32'
  ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
  : path.join(repoRoot, '.venv', 'bin', 'python')
const lifecycleEnvironment = consumeLifecycleEnvironment()
let child
try {
  child = spawn(
    python,
    lifecycleEnvironment
      ? ['-m', 'services.api.app.managed_server']
      : ['-m', 'uvicorn', 'services.api.app.main:app', '--host', '127.0.0.1', '--port', String(api), '--reload'],
    {
      cwd: repoRoot,
      stdio: 'inherit',
      shell: false,
      env: lifecycleEnvironment?.childEnvironment ?? process.env,
    },
  )
} finally {
  lifecycleEnvironment?.release()
}

const stop = () => stopChildTree(child)
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
child.on('error', error => {
  console.error(`InMyAI API failed to start: ${error.message}`)
  process.exitCode = 1
})
child.on('exit', (code, signal) => {
  process.exitCode = signal ? 1 : (code ?? 1)
})
