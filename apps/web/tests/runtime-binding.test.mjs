import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const packagePath = path.resolve(here, '..', 'package.json')

test('web dev and start scripts bind explicitly to loopback', async () => {
  const packageJson = JSON.parse(await readFile(packagePath, 'utf8'))
  assert.equal(packageJson.scripts.dev, 'next dev -H 127.0.0.1')
  assert.equal(packageJson.scripts.start, 'next start -H 127.0.0.1')
})
