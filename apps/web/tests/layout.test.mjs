import test from 'node:test'
import assert from 'node:assert/strict'
import { clampPanelWidth, SIDEBAR_MIN, SIDEBAR_MAX, RAIL_MIN, RAIL_MAX } from '../src/lib/layout.ts'

test('clampPanelWidth keeps values inside range unchanged', () => {
  assert.equal(clampPanelWidth(250, SIDEBAR_MIN, SIDEBAR_MAX), 250)
})

test('clampPanelWidth floors a value below the minimum', () => {
  assert.equal(clampPanelWidth(10, SIDEBAR_MIN, SIDEBAR_MAX), SIDEBAR_MIN)
})

test('clampPanelWidth ceils a value above the maximum', () => {
  assert.equal(clampPanelWidth(9999, SIDEBAR_MIN, SIDEBAR_MAX), SIDEBAR_MAX)
})

test('clampPanelWidth works independently for the rail range', () => {
  assert.equal(clampPanelWidth(50, RAIL_MIN, RAIL_MAX), RAIL_MIN)
  assert.equal(clampPanelWidth(5000, RAIL_MIN, RAIL_MAX), RAIL_MAX)
})

test('clampPanelWidth falls back to the minimum for NaN (a bad drag delta)', () => {
  assert.equal(clampPanelWidth(Number.NaN, SIDEBAR_MIN, SIDEBAR_MAX), SIDEBAR_MIN)
})
