/**
 * Onboarding wizard state helpers.
 *
 * The wizard auto-shows when Ollama is not usable (unavailable, or running
 * without any model). A user can dismiss it; the dismissal is remembered in
 * localStorage so the wizard does not nag on every load. Mirrors the
 * inmyai:<feature> key convention from chat-history.ts.
 */
const DISMISSED_KEY = 'inmyai:onboarding:dismissed'

export function onboardingDismissedKey(): string {
  return DISMISSED_KEY
}

/** True when the wizard should appear: Ollama not usable AND not dismissed. */
export function shouldShowWizard(ollamaAvailable: boolean, modelsCount: number): boolean {
  const usable = ollamaAvailable && modelsCount > 0
  if (usable) return false
  return !isOnboardingDismissed()
}

export function isOnboardingDismissed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === 'true'
  } catch {
    return false
  }
}

export function dismissOnboarding(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(DISMISSED_KEY, 'true')
  } catch {
    /* ignore quota / privacy-mode failures */
  }
}

export function resetOnboardingDismissed(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(DISMISSED_KEY)
  } catch {
    /* ignore */
  }
}
