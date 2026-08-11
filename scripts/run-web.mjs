import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import {
  assertLoopbackPortAvailable,
  resolveInMyAIPorts,
  resolveWebEnvironment,
} from './ports.mjs'
import { stopChildTree } from './process-tree.mjs'

const mode = process.argv[2]
if (!['dev', 'start'].includes(mode)) {
  throw new Error('InMyAI web launcher mode must be "dev" or "start".')
}

const { web } = resolveInMyAIPorts()
await assertLoopbackPortAvailable('INMYAI_WEB_PORT', web)
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const webRoot = path.join(repoRoot, 'apps', 'web')
const require = createRequire(import.meta.url)
const nextBin = require.resolve('next/dist/bin/next')
const environment = resolveWebEnvironment(process.env)

const child = spawn(
  process.execPath,
  [nextBin, mode, '-H', '127.0.0.1', '-p', String(web)],
  { cwd: webRoot, env: environment, stdio: 'inherit', shell: false },
)

const stop = () => stopChildTree(child)
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
child.on('error', error => {
  console.error(`InMyAI web failed to start: ${error.message}`)
  process.exitCode = 1
})
child.on('exit', (code, signal) => {
  process.exitCode = signal ? 1 : (code ?? 1)
})
