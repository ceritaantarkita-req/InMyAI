import { spawn } from 'node:child_process'
import process from 'node:process'

const python = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'
const api = spawn(python, ['-m', 'uvicorn', 'services.api.app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload'], { stdio: 'inherit', shell: process.platform === 'win32' })
const web = spawn('npm', ['--workspace', 'apps/web', 'run', 'dev'], { stdio: 'inherit', shell: process.platform === 'win32' })

const stop = () => { api.kill('SIGTERM'); web.kill('SIGTERM') }
process.on('SIGINT', () => { stop(); process.exit(0) })
process.on('SIGTERM', () => { stop(); process.exit(0) })
api.on('exit', (code) => { if (code && code !== 0) { web.kill('SIGTERM'); process.exit(code) } })
web.on('exit', (code) => { if (code && code !== 0) { api.kill('SIGTERM'); process.exit(code) } })
