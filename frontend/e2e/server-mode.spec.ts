import { expect, test } from '@playwright/test'

const API = process.env.LINEZERO_API ?? 'http://127.0.0.1:8000'

test.describe('with the backend running', () => {
  test.beforeAll(async ({ request }) => {
    const ok = await request.get(`${API}/health`).then(r => r.ok()).catch(() => false)
    test.skip(!ok, `backend not reachable at ${API}`)
  })
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('lz.source', 'server'))
  })

  test('analytics loads from the API and labels synthetic data', async ({ page }) => {
    await page.goto('/app/analytics')
    await expect(page.locator('.live-pill').first()).toContainText('Server API')
    await expect(page.getByText('Synthetic data').first()).toBeVisible()
    await expect(page.getByText('Utilization by counter')).toBeVisible()
  })

  test('simulator runs and compares on the server', async ({ page }) => {
    await page.goto('/app/simulator')
    await page.getByRole('button', { name: 'Run simulation' }).click()
    await expect(page.getByText('Theoretical comparison')).toBeVisible()
    await page.getByRole('button', { name: /Compare with/ }).click()
    await expect(page.getByRole('cell', { name: '6 counters' }).first()).toBeVisible()
  })

  test('bottleneck analysis returns findings for the capacity-starved queue', async ({ page }) => {
    await page.goto('/app/bottlenecks')
    await page.getByLabel('Server queue').selectOption({ label: '[SYNTHETIC] Insufficient capacity · 3 counters' })
    await page.getByRole('button', { name: 'Analyze queue' }).first().click()
    await expect(page.getByText('Capacity / demand imbalance')).toBeVisible()
  })

  test('report can be generated and listed', async ({ page }) => {
    await page.goto('/app/reports')
    await page.getByRole('button', { name: 'Generate report' }).click()
    await expect(page.getByText('Report generated')).toBeVisible()
  })
})

test('falls back to demo data when the API is unreachable', async ({ page }) => {
  await page.route('**/health', r => r.abort())
  await page.route('**/api/v1/**', r => r.abort())
  await page.addInitScript(() => localStorage.setItem('lz.source', 'server'))
  await page.goto('/app/analytics')
  await expect(page.locator('.live-pill').first()).toContainText('API offline')
  await expect(page.getByText('Demo data').first()).toBeVisible()
})
