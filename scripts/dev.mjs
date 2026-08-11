import { spawn } from 'node:child_process'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { assertLoopbackPortAvailable, resolveInMyAIPorts } from './ports.mjs'
import { stopChildTree } from './process-tree.mjs'

const ports = resolveInMyAIPorts()
await assertLoopbackPortAvailable('INMYAI_WEB_PORT', ports.web)
await assertLoopbackPortAvailable('INMYAI_API_PORT', ports.api)
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = process.platform === 'win32'
  ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
  : path.join(repoRoot, '.venv', 'bin', 'python')
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const api = spawn(python, ['-m', 'uvicorn', 'services.api.app.main:app', '--host', '127.0.0.1', '--port', String(ports.api), '--reload'], { cwd: repoRoot, stdio: 'inherit', shell: false })
const web = spawn(npm, ['--workspace', 'apps/web', 'run', 'dev'], { cwd: repoRoot, stdio: 'inherit', shell: process.platform === 'win32' })

const stop = () => { stopChildTree(api); stopChildTree(web) }
process.on('SIGINT', () => { stop(); process.exit(0) })
process.on('SIGTERM', () => { stop(); process.exit(0) })
api.on('exit', (code) => { if (code && code !== 0) { stopChildTree(web); process.exit(code) } })
web.on('exit', (code) => { if (code && code !== 0) { stopChildTree(api); process.exit(code) } })
