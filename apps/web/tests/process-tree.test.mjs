import test from 'node:test'
import assert from 'node:assert/strict'
import { childStopCommand } from '../../../scripts/process-tree.mjs'

test('Windows child cleanup is scoped to the spawned PID tree', () => {
  assert.deepEqual(childStopCommand('win32', 1234), {
    command: 'taskkill.exe',
    args: ['/PID', '1234', '/T', '/F'],
  })
})

test('POSIX child cleanup uses SIGTERM without a shell command', () => {
  assert.deepEqual(childStopCommand('linux', 1234), {
    command: null,
    args: [],
  })
})
