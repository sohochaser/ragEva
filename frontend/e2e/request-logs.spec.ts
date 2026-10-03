import { expect, test } from '@playwright/test'

test('System Status finds an API error by request ID', async ({ page }) => {
  const response = await page.request.post('/api/v1/runs', { data: { prediction_batch_id: '' } })
  expect(response.status()).toBe(422)
  const requestId = response.headers()['x-request-id']
  expect(requestId).toMatch(/^[0-9a-f]{32}$/)

  await page.goto('/')
  await page.getByRole('navigation', { name: /主导航/ }).getByRole('button', { name: /系统状态/ }).click()
  await page.getByLabel('Request ID（请求 ID）').fill(requestId)
  await page.getByRole('button', { name: 'Find（查找）' }).click()
  const timeline = page.locator('.request-log-timeline')
  await expect(timeline.getByText('http.request')).toBeVisible()
  await expect(timeline.getByText(/http_422/)).toBeVisible()
  await expect(page.locator('.request-log-detail-heading')).toContainText('HTTP 422')
})
