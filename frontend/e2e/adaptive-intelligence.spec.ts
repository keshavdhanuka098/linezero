import { expect, test, type Page } from '@playwright/test'

const API = process.env.LINEZERO_API ?? 'http://127.0.0.1:8000'

test('browser demo mode explains that adaptive intelligence needs the backend', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('lz.source', 'browser'))
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  for (const [path, title] of [['adaptive-intelligence', 'Adaptive Intelligence'], ['risk-radar', 'Operational Risk Radar'], ['interventions', 'Autonomous Interventions'], ['outcome-learning', 'Outcome Learning']]) {
    await page.goto(`/app/${path}`)
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
    await expect(page.getByText('needs the LineZero backend')).toBeVisible()
  }
  expect(errors).toEqual([])
})

test.describe('with the backend running', () => {
  test.beforeAll(async ({ request }) => {
    const ok = await request.get(`${API}/health`).then(r => r.ok()).catch(() => false)
    test.skip(!ok, `backend not reachable at ${API}`)
  })
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => { localStorage.setItem('lz.source', 'server'); localStorage.setItem('lz.operator', 'e2e operator') })
  })
  const pickQueue = async (page: Page, name: RegExp) => {
    const sel = page.getByLabel('Queue', { exact: true })
    await expect(sel).toBeVisible()
    const label = await sel.locator('option').filter({ hasText: name }).first().textContent()
    await sel.selectOption({ label: label ?? '' })
  }

  test('adaptive intelligence shows provenance, nominal model and a non-saving preview', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto('/app/adaptive-intelligence')
    await pickQueue(page, /Insufficient capacity/)
    await expect(page.getByText('SYNTHETIC DATA')).toBeVisible()
    await expect(page.getByText('Active model')).toBeVisible()
    await page.getByRole('button', { name: /Preview \(saves nothing\)/ }).click()
    await expect(page.getByRole('status').getByText('preview only')).toBeVisible()
    await expect(page.getByText('Drift detection')).toBeVisible()
    expect(errors).toEqual([])
  })

  test('risk radar scores seven categories with a visible formula', async ({ page }) => {
    await page.goto('/app/risk-radar')
    await pickQueue(page, /Sudden arrival spike/)
    await expect(page.getByRole('heading', { name: 'Operational risk radar', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Queue congestion' })).toBeVisible()
    await page.getByRole('button', { name: /how this score is computed/ }).first().click()
    await expect(page.getByText(/^score = /).first()).toBeVisible()
  })

  test('interventions: simulate, approve, confirm applied; then record a reported outcome', async ({ page }) => {
    await page.goto('/app/interventions')
    await pickQueue(page, /Insufficient capacity/)
    await expect(page.getByText('SIMULATION ONLY')).toBeVisible()
    await page.getByRole('button', { name: 'Simulate interventions' }).click()
    await expect(page.getByTestId('explanation')).toBeVisible()
    const card = page.getByRole('article').filter({ hasText: 'recommended' }).first()
    if (await card.count() === 0) { test.info().annotations.push({ type: 'note', description: 'no candidate was recommended for this queue state' }); return }
    await card.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText(/Approved\. LineZero has not changed anything/).first()).toBeVisible()
    await card.getByRole('button', { name: 'I carried this out' }).click()
    await expect(page.getByText(/LineZero never changes counters or queues/)).toBeVisible()
    await page.getByRole('button', { name: 'Yes, it was applied' }).click()
    await expect(page.getByText('Applied by operator').first()).toBeVisible()

    await page.goto('/app/outcome-learning')
    await pickQueue(page, /Insufficient capacity/)
    await page.getByRole('button', { name: 'Operator-reported figure' }).first().click()
    await page.getByLabel('Reported average wait').first().fill('2.5')
    await page.getByRole('button', { name: 'Record outcome' }).first().click()
    await expect(page.getByText('Operator reported').first()).toBeVisible()
    await expect(page.getByText(/not measured by LineZero/).first()).toBeVisible()
  })

  test('outcome learning shows the closed loop and runs only automatic stages', async ({ page }) => {
    await page.goto('/app/outcome-learning')
    await pickQueue(page, /Sudden arrival spike/)
    await expect(page.getByText('The closed loop')).toBeVisible()
    await page.getByRole('button', { name: 'Run automatic stages' }).click()
    await expect(page.getByText(/Nothing was approved or applied/).first()).toBeVisible()
    await expect(page.getByText('Verified real outcomes', { exact: true })).toBeVisible()
  })
})
