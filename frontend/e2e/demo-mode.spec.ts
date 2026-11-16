import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('lz.source', 'browser'))
})

const pages = ['dashboard', 'monitor', 'analytics', 'simulator', 'bottlenecks', 'optimizer', 'reports', 'settings']

for (const p of pages) {
  test(`demo page renders without errors: ${p}`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(`/app/${p}`)
    await expect(page.locator('h1').first()).toBeVisible()
    await expect(page.locator('.live-pill').first()).toContainText('Browser demo')
    expect(errors).toEqual([])
  })
}

test('landing page enters the app', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/LineZero/)
})

test('unknown app route shows the not-found state', async ({ page }) => {
  await page.goto('/app/nope')
  await expect(page.getByText('Page not found')).toBeVisible()
})
