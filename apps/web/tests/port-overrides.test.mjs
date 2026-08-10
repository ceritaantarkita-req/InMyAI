import test from 'node:test'
import assert from 'node:assert/strict'
import net from 'node:net'
import {
  assertLoopbackPortAvailable,
  parsePortOverride,
  resolveInMyAIPorts,
  resolveWebEnvironment,
} from '../../../scripts/ports.mjs'

test('InMyAI keeps legacy defaults and accepts the canonical G3 opt-ins', () => {
  assert.deepEqual(resolveInMyAIPorts({}), { web: 3000, api: 8000 })
  assert.deepEqual(resolveInMyAIPorts({
    INMYAI_WEB_PORT: '17001',
    INMYAI_API_PORT: '17002',
  }), { web: 17001, api: 17002 })
})

test('web follows the API opt-in unless an explicit public API URL is supplied', () => {
  assert.equal(
    resolveWebEnvironment({ INMYAI_API_PORT: '17002' }).NEXT_PUBLIC_API_URL,
    'http://127.0.0.1:17002',
  )
  assert.equal(
    resolveWebEnvironment({
      INMYAI_API_PORT: '17002',
      NEXT_PUBLIC_API_URL: 'http://127.0.0.1:9000',
    }).NEXT_PUBLIC_API_URL,
    'http://127.0.0.1:9000',
  )
})

test('InMyAI port overrides reject invalid values before startup', () => {
  for (const value of ['', ' ', '0', '-1', '1.5', 'abc', '65536']) {
    assert.throws(
      () => parsePortOverride('INMYAI_WEB_PORT', value, 3000),
      /INMYAI_WEB_PORT must be an integer between 1 and 65535/,
    )
    assert.throws(
      () => parsePortOverride('INMYAI_API_PORT', value, 8000),
      /INMYAI_API_PORT must be an integer between 1 and 65535/,
    )
  }
})

test('InMyAI rejects an occupied loopback port before starting a runtime', async t => {
  const blocker = net.createServer()
  await new Promise((resolve, reject) => {
    blocker.once('error', reject)
    blocker.listen({ host: '127.0.0.1', port: 0, exclusive: true }, resolve)
  })
  t.after(() => blocker.close())
  const address = blocker.address()
  assert.equal(typeof address, 'object')

  await assert.rejects(
    assertLoopbackPortAvailable('INMYAI_API_PORT', address.port),
    /INMYAI_API_PORT cannot bind 127\.0\.0\.1:\d+: EADDRINUSE/,
  )
})
