import { expect, test } from '@playwright/test'

const API = process.env.LINEZERO_API ?? 'http://127.0.0.1:8000'

test('browser demo mode explains that the twin needs the backend', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('lz.source', 'browser'))
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/app/digital-twin')
  await expect(page.getByRole('heading', { name: 'Digital Twin' })).toBeVisible()
  await expect(page.getByText('needs the LineZero backend')).toBeVisible()
  expect(errors).toEqual([])
})

test.describe('with the backend running', () => {
  test.beforeAll(async ({ request }) => {
    const ok = await request.get(`${API}/health`).then(r => r.ok()).catch(() => false)
    test.skip(!ok, `backend not reachable at ${API}`)
  })
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('lz.source', 'server'))
  })

  test('live twin shows real queue state and a four-horizon forecast', async ({ page }) => {
    await page.goto('/app/digital-twin')
    await expect(page.getByText('Forecast: 5, 15, 30 and 60 minutes')).toBeVisible()
    await expect(page.getByText('+60 min')).toBeVisible()
  })

  test('a predefined chaos scenario runs and exposes playback controls and a timeline', async ({ page }) => {
    await page.goto('/app/digital-twin')
    await page.getByRole('button', { name: 'What-if & chaos' }).click()
    await page.getByRole('button', { name: 'Counter failure' }).first().click()
    await expect(page.getByRole('button', { name: /Pause|Resume|Play/ }).first()).toBeVisible()
    await expect(page.getByText('Simulation timeline')).toBeVisible()
    await page.getByRole('button', { name: 'Reset' }).click()
  })

  test('self-healing recommends interventions by simulation', async ({ page }) => {
    await page.goto('/app/digital-twin')
    await page.getByRole('button', { name: 'Self-healing' }).click()
    await page.getByRole('button', { name: 'Diagnose and recommend' }).click()
    await expect(page.getByText('Diagnosis')).toBeVisible()
  })

  test('explain works without a Gemini key', async ({ page }) => {
    await page.goto('/app/digital-twin')
    await page.getByRole('button', { name: 'Explain', exact: true }).click()
    await page.getByRole('button', { name: 'Why did congestion occur?' }).click()
    await expect(page.getByText('Built-in explainer').or(page.getByText('Gemini (numbers verified)'))).toBeVisible()
  })
})
