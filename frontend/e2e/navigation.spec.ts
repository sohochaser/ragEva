import { expect, test } from '@playwright/test'

const pages = [
  'Document Collections（文档集合）', 'Candidate Generation（候选生成）', 'Datasets（数据集）',
  'Prediction Batches（预测批次）', 'HTTP Targets（HTTP 目标）', 'Evaluation Scenarios（评价场景）',
  'Evaluation Runs（评测运行）', 'System Status（系统状态）',
]

test('desktop navigation reaches every workspace', async ({ page }) => {
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: /主导航/ })
  await expect(nav).toBeVisible()
  await expect(page.getByRole('button', { name: /打开导航/ })).toBeHidden()

  for (const name of pages) {
    const item = nav.getByRole('button', { name })
    await item.click()
    await expect(item).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible()
  }
})

test('compact navigation opens, closes and reaches every workspace', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: /主导航/ })
  await expect(nav).toBeHidden()

  for (const name of pages) {
    await page.getByRole('button', { name: /打开导航/ }).click()
    await expect(nav).toBeVisible()
    await nav.getByRole('button', { name }).click()
    await expect(nav).toBeHidden()
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible()
  }
})

for (const width of [320, 390, 768, 1440]) {
  test(`every workspace fits the ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    const nav = page.getByRole('navigation', { name: /主导航/ })

    for (const name of pages) {
      if (width <= 640) await page.getByRole('button', { name: /打开导航/ }).click()
      await nav.getByRole('button', { name }).click()
      const heading = page.getByRole('heading', { name, exact: true, level: 1 })
      await expect(heading).toBeVisible()
      const bounds = await heading.boundingBox()
      expect(bounds).not.toBeNull()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
      for (const action of await page.locator('.page-header button').all()) {
        const actionBounds = await action.boundingBox()
        if (!actionBounds) continue
        const overlaps = bounds!.x < actionBounds.x + actionBounds.width
          && bounds!.x + bounds!.width > actionBounds.x
          && bounds!.y < actionBounds.y + actionBounds.height
          && bounds!.y + bounds!.height > actionBounds.y
        expect(overlaps).toBe(false)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    }
  })
}

test('compact menu supports keyboard opening and dismissal', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/')
  const menu = page.getByRole('button', { name: /打开导航/ })
  await menu.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('navigation', { name: /主导航/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('navigation', { name: /主导航/ })).toBeHidden()
  await expect(menu).toBeFocused()
})
