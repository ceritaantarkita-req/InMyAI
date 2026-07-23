import test from 'node:test'
import assert from 'node:assert/strict'

import { onboardingDismissedKey, shouldShowWizard, isOnboardingDismissed, dismissOnboarding } from '../src/lib/onboarding.ts'

test('onboardingDismissedKey is namespaced under inmyai', () => {
  assert.equal(onboardingDismissedKey(), 'inmyai:onboarding:dismissed')
})

test('shouldShowWizard is true when ollama is unavailable regardless of models', () => {
  assert.equal(shouldShowWizard(false, 0), true)
  assert.equal(shouldShowWizard(false, 5), true)
})

test('shouldShowWizard is true when ollama is running but no model is installed', () => {
  assert.equal(shouldShowWizard(true, 0), true)
})

test('shouldShowWizard is false when ollama is running and at least one model exists', () => {
  assert.equal(shouldShowWizard(true, 1), false)
  assert.equal(shouldShowWizard(true, 7), false)
})

test('isOnboardingDismissed returns false in non-browser (SSR guard)', () => {
  // In the Node test runner there is no window, so the helpers must not throw
  // and must report 'not dismissed' rather than touching storage.
  assert.equal(isOnboardingDismissed(), false)
  // dismissOnboarding must be a safe no-op without window.
  assert.doesNotThrow(() => dismissOnboarding())
})

test('onboardingDismissedKey matches the documented namespace', () => {
  assert.match(onboardingDismissedKey(), /^inmyai:/)
})
