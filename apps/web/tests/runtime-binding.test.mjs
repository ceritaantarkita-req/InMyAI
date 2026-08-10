import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const packagePath = path.resolve(here, '..', 'package.json')
const rootPackagePath = path.resolve(here, '..', '..', '..', 'package.json')

test('web and API launchers use the validated loopback port wrappers', async () => {
  const packageJson = JSON.parse(await readFile(packagePath, 'utf8'))
  const rootPackageJson = JSON.parse(await readFile(rootPackagePath, 'utf8'))

  assert.equal(packageJson.scripts.dev, 'node ../../scripts/run-web.mjs dev')
  assert.equal(packageJson.scripts.start, 'node ../../scripts/run-web.mjs start')
  assert.equal(rootPackageJson.scripts['dev:api'], 'node scripts/run-api.mjs')
})
