import { existsSync, copyFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

const run = (command, args) => {
  const result = spawnSync(command, args, { stdio: 'inherit', shell: process.platform === 'win32' })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

if (!existsSync('.env')) copyFileSync('.env.example', '.env')
run('npm', ['install', '--no-audit', '--no-fund'])
if (!existsSync('.venv')) run(process.platform === 'win32' ? 'python' : 'python3', ['-m', 'venv', '.venv'])
const python = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'
run(python, ['-m', 'pip', 'install', '-r', 'services/api/requirements.txt'])
console.log('\nSetup complete. Run: npm run dev')
