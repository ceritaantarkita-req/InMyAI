import assert from 'node:assert/strict'
import test from 'node:test'
import { consumeLifecycleEnvironment } from '../../../scripts/lifecycle-environment.mjs'

test('managed launch passes the token once without retaining it in the Node environment', () => {
  const parentEnvironment = {
    PATH: 'synthetic-path',
    INMY_LIFECYCLE_SHUTDOWN_TOKEN: 'manager-generated-test-token',
  }

  const consumed = consumeLifecycleEnvironment(parentEnvironment)
  assert.ok(consumed)
  assert.equal(parentEnvironment.INMY_LIFECYCLE_SHUTDOWN_TOKEN, undefined)
  assert.equal(consumed.childEnvironment.INMY_LIFECYCLE_SHUTDOWN_TOKEN, 'manager-generated-test-token')
  assert.equal(consumed.childEnvironment.PATH, 'synthetic-path')

  consumed.release()
  assert.equal(consumed.childEnvironment.INMY_LIFECYCLE_SHUTDOWN_TOKEN, undefined)
})

test('unmanaged launch leaves a tokenless environment unchanged', () => {
  const environment = { PATH: 'synthetic-path' }

  assert.equal(consumeLifecycleEnvironment(environment), null)
  assert.deepEqual(environment, { PATH: 'synthetic-path' })
})
