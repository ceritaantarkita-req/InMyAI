import test from 'node:test'
import assert from 'node:assert/strict'

test('core navigation lists the primary work surfaces without duplicates', () => {
  const views = ['chat', 'files', 'memory', 'graph', 'studio', 'git', 'agents', 'explorer', 'terminal']
  assert.equal(new Set(views).size, views.length)
})

test('public API URL has a safe local default', () => {
  const value = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'
  assert.match(value, /^https?:\/\//)
})
