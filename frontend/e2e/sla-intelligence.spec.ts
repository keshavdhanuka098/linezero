import { expect, test } from '@playwright/test'

const API = process.env.LINEZERO_API ?? 'http://127.0.0.1:8000'

test('browser demo mode explains that SLA intelligence needs the backend', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('lz.source', 'browser'))
  await page.goto('/app/sla-intelligence')
  await expect(page.getByRole('heading', { name: 'SLA Intelligence', exact: true })).toBeVisible()
  await expect(page.getByText('needs the LineZero backend')).toBeVisible()
})

test.describe('with the backend running', () => {
  test.beforeAll(async ({ request }) => {
    const ok = await request.get(`${API}/health`).then(r => r.ok()).catch(() => false)
    test.skip(!ok, `backend not reachable at ${API}`)
  })
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => { localStorage.setItem('lz.source', 'server'); localStorage.setItem('lz.operator', 'e2e operator') })
  })

  test('an operator sets a target, sees live customers and gets a validated recommendation', async ({ page, request }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    const name = `SLA e2e ${Date.now()}`
    const q = await (await request.post(`${API}/api/v1/queues`, { data: { name } })).json()
    await request.post(`${API}/api/v1/queues/${q.id}/counters`, { data: { name: 'C1' } })
    for (let i = 0; i < 4; i++) await request.post(`${API}/api/v1/queues/${q.id}/entries`)

    await page.goto('/app/sla-intelligence')
    const sel = page.getByLabel('Queue', { exact: true })
    await expect(sel).toBeVisible()
    await sel.selectOption({ label: await sel.locator('option').filter({ hasText: name }).first().textContent() ?? '' })

    await expect(page.getByText('Set an SLA target to begin')).toBeVisible()
    await page.getByRole('button', { name: 'Configure targets' }).click()
    await page.getByRole('button', { name: /Set standard target/ }).click()
    await page.getByLabel('Maximum wait in minutes').fill('1')
    await page.getByRole('button', { name: 'Save target' }).click()
    await expect(page.getByRole('cell', { name: '1 min' })).toBeVisible()

    await page.getByRole('button', { name: /Live customers/ }).click()
    await expect(page.locator('.sla-row').first()).toBeVisible()

    await page.getByRole('button', { name: 'Recommendations' }).click()
    await page.getByRole('button', { name: /Run simulation|Evaluate|Recommend/ }).first().click()
    await expect(page.getByText(/simulated/i).first()).toBeVisible()
    expect(errors).toEqual([])
  })
})
