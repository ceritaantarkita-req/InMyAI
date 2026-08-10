import { spawnSync } from 'node:child_process'
import process from 'node:process'

export function childStopCommand(platform, pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) {
    throw new Error('Child PID must be a positive integer.')
  }
  if (platform === 'win32') {
    return {
      command: 'taskkill.exe',
      args: ['/PID', String(pid), '/T', '/F'],
    }
  }
  return { command: null, args: [] }
}

export function stopChildTree(child, platform = process.platform) {
  if (!child?.pid) return
  const specification = childStopCommand(platform, child.pid)
  if (specification.command) {
    spawnSync(specification.command, specification.args, {
      stdio: 'ignore',
      windowsHide: true,
    })
  } else {
    child.kill('SIGTERM')
  }
}
