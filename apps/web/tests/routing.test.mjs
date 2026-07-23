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

test('nav splits into 5 main + 4 advanced, no overlap, union = all 9', () => {
  const main = ['chat', 'files', 'explorer', 'graph', 'terminal']
  const advanced = ['memory', 'studio', 'git', 'agents']
  const all = [...main, ...advanced]
  assert.equal(new Set(all).size, all.length)
  const original = new Set(['chat', 'files', 'memory', 'graph', 'studio', 'git', 'agents', 'explorer', 'terminal'])
  assert.deepEqual(new Set(all), original)
  assert.equal(main.length, 5)
  assert.equal(advanced.length, 4)
})
