/**
 * Tiny gate shared by the splash screen and the landing page.
 * The landing hero intro waits on `whenSplashDone()` so it plays *after* the
 * loading screen lifts instead of running hidden underneath it.
 */
let done = false
let begun = false
let resolveFn: (() => void) | null = null
const gate = new Promise<void>(res => { resolveFn = res })

export const SPLASH_MS = 3600 // total time on screen, fade-out included (3–4 s target)
export const SPLASH_FADE_MS = 650

export function shouldShowSplash(): boolean {
  if (typeof window === 'undefined') return false
  // Automated browsers (Playwright e2e) skip it so tests are not blocked by the overlay.
  if (typeof navigator !== 'undefined' && navigator.webdriver) return false
  return true // shown on every full page load; in-app navigation never remounts it
}

export function beginSplash(): void { begun = true }

export function finishSplash(): void {
  if (done) return
  done = true
  resolveFn?.()
}

/** Resolves immediately when no splash is running. */
export function whenSplashDone(): Promise<void> {
  return begun && !done ? gate : Promise.resolve()
}
