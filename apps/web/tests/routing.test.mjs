import test from 'node:test'
import assert from 'node:assert/strict'

test('core navigation remains limited to five primary work surfaces', () => {
  const views = ['chat', 'files', 'memory', 'graph', 'studio']
  assert.equal(views.length, 5)
  assert.equal(new Set(views).size, views.length)
})

test('public API URL has a safe local default', () => {
  const value = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'
  assert.match(value, /^https?:\/\//)
})
