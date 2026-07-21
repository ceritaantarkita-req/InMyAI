import { spawnSync } from 'node:child_process'
import process from 'node:process'

const run = (command, args) => {
  console.log(`\n> ${command} ${args.join(' ')}`)
  const result = spawnSync(command, args, { stdio: 'inherit', shell: process.platform === 'win32' })
  if (result.status !== 0) process.exit(result.status ?? 1)
}
const python = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python'
run('npm', ['run', 'typecheck:web'])
run('npm', ['run', 'test:web'])
run(python, ['-m', 'pytest', 'services/api/tests', '-q'])
run('npm', ['run', 'build:web'])
console.log('\nQA passed. Real Ollama and image-model quality require separate hardware/provider acceptance tests.')
