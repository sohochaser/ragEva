import { expect, test } from '@playwright/test'

test('selects an existing collection, appends, and keeps both snapshots', async ({ page, request }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /上传原文/ }).click()
  let dialog = page.getByRole('dialog', { name: /上传原文/ })
  await dialog.getByRole('combobox', { name: /集合名称/ }).fill('Append E2E')
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'first.txt', mimeType: 'text/plain', buffer: Buffer.from('First source'),
  })
  await dialog.getByRole('button', { name: 'Upload（上传）' }).click()
  await expect(dialog).toBeHidden()
  const firstList = await (await request.get('/api/v1/document-collections')).json() as Array<{ id: string; group_id: string; name: string }>
  const first = firstList.find((item) => item.name === 'Append E2E')!

  await page.getByRole('button', { name: /上传原文/ }).click()
  dialog = page.getByRole('dialog', { name: /上传原文/ })
  const picker = dialog.getByRole('combobox', { name: /集合名称/ })
  await picker.fill('Append')
  await picker.press('ArrowDown')
  await picker.press('Enter')
  await expect(dialog.getByRole('status')).toContainText('Append to Append E2E')
  await expect(dialog.getByRole('spinbutton', { name: /切块大小/ })).toBeDisabled()
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'second.txt', mimeType: 'text/plain', buffer: Buffer.from('Second source'),
  })
  await dialog.getByRole('button', { name: 'Upload（上传）' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator('.dataset-toolbar')).toContainText('Added（新增） 1 document IDs（文档 ID）')
  await expect(page.locator('.dataset-toolbar')).toContainText('Total（累计） 2 document IDs（文档 ID）')
  const latestList = await (await request.get('/api/v1/document-collections')).json() as Array<{ id: string; group_id: string; name: string; version: number }>
  const latest = latestList.find((item) => item.name === 'Append E2E')!
  expect(latestList.filter((item) => item.name === 'Append E2E')).toHaveLength(1)
  expect(latest.group_id).toBe(first.group_id)
  expect(latest.version).toBe(2)
  const headers = { Authorization: 'Bearer browser-e2e-token' }
  const oldManifest = await (await request.get(`http://127.0.0.1:18001/download/v1/collections/${first.id}/manifest`, { headers })).json() as { documents: unknown[] }
  const newManifest = await (await request.get(`http://127.0.0.1:18001/download/v1/collections/${latest.id}/manifest`, { headers })).json() as { documents: unknown[] }
  expect(oldManifest.documents).toHaveLength(1)
  expect(newManifest.documents).toHaveLength(2)
  await page.getByRole('combobox', { name: /快照版本/ }).selectOption(first.id)
  await expect(page.locator('.document-detail')).toHaveCount(1)
  await page.getByRole('combobox', { name: /快照版本/ }).selectOption(latest.id)
  await expect(page.locator('.document-detail')).toHaveCount(2)

  await page.getByRole('button', { name: /导入 chunk 清单/ }).click()
  let chunks = page.getByRole('dialog', { name: /导入 chunk 清单/ })
  await chunks.getByRole('combobox', { name: /集合名称/ }).fill('Chunk E2E')
  await chunks.locator('input[type=file]').setInputFiles({
    name: 'first.csv', mimeType: 'text/csv', buffer: Buffer.from('position,document_id,text\n0,doc-a,First chunk\n'),
  })
  await chunks.getByRole('button', { name: 'Import（导入）' }).click()
  await expect(chunks).toBeHidden()
  await page.getByRole('button', { name: /导入 chunk 清单/ }).click()
  chunks = page.getByRole('dialog', { name: /导入 chunk 清单/ })
  await chunks.getByRole('combobox', { name: /集合名称/ }).fill('Chunk E2E')
  await expect(chunks.getByRole('status')).toContainText('Append to Chunk E2E')
  await chunks.locator('input[type=file]').setInputFiles({
    name: 'second.csv', mimeType: 'text/csv', buffer: Buffer.from('position,document_id,text\n0,doc-b,Second chunk\n'),
  })
  await chunks.getByRole('button', { name: 'Import（导入）' }).click()
  await expect(chunks).toBeHidden()
  await expect(page.locator('.chunk-list li')).toHaveCount(2)
  await expect(page.locator('.chunk-list li').nth(1)).toContainText('doc-b')
  await page.setViewportSize({ width: 320, height: 700 })
  await page.getByRole('button', { name: /上传原文/ }).click()
  dialog = page.getByRole('dialog', { name: /上传原文/ })
  await dialog.getByRole('combobox', { name: /集合名称/ }).fill('Append')
  await expect(dialog.getByRole('option', { name: /Append E2E/ })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
