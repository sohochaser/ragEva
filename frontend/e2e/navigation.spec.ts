import { expect, test } from '@playwright/test'

const pages = ['文档集合', '候选生成', '数据集', '预测批次', 'HTTP 目标', '评价场景', '评测运行', '系统状态']

test('desktop navigation reaches every workspace', async ({ page }) => {
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: '主导航' })
  await expect(nav).toBeVisible()
  await expect(page.getByRole('button', { name: '打开导航' })).toBeHidden()

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
  const nav = page.getByRole('navigation', { name: '主导航' })
  await expect(nav).toBeHidden()

  for (const name of pages) {
    await page.getByRole('button', { name: '打开导航' }).click()
    await expect(nav).toBeVisible()
    await nav.getByRole('button', { name }).click()
    await expect(nav).toBeHidden()
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible()
  }
})
