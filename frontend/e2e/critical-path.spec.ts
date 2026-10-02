import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

const source = 'Acme launched in 2018.'

async function navigate(page: Page, name: string) {
  await page.getByRole('navigation', { name: /主导航/ }).getByRole('button', { name: new RegExp(name) }).click()
}

test('document, generation, target, file and answer run paths', async ({ page, request }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /文档集合/ })).toBeVisible()
  await page.getByRole('button', { name: /上传原文/ }).click()
  const upload = page.getByRole('dialog', { name: /上传原文/ })
  await upload.getByLabel('Collection Name（集合名称）').fill('E2E Sources')
  await upload.locator('input[type=file]').setInputFiles({ name: 'acme.txt', mimeType: 'text/plain', buffer: Buffer.from(source) })
  await upload.getByPlaceholder('Auto Generate（自动生成）').fill('doc-a')
  await upload.getByRole('button', { name: 'Upload（上传）' }).click()
  await expect(page.locator('.document-detail')).toContainText(source)

  const collectionResponse = await request.get('/api/v1/document-collections')
  expect(collectionResponse.ok()).toBeTruthy()
  const [collection] = await collectionResponse.json() as Array<{ id: string }>
  const manifestUrl = `http://127.0.0.1:18001/download/v1/collections/${collection.id}/manifest`
  expect((await request.get(manifestUrl)).status()).toBe(401)
  const headers = { Authorization: 'Bearer browser-e2e-token' }
  const manifestResponse = await request.get(manifestUrl, { headers })
  expect(manifestResponse.ok()).toBeTruthy()
  const manifest = await manifestResponse.json() as { documents: Array<{ document_id: string; download_url: string }> }
  expect(manifest.documents[0].document_id).toBe('doc-a')
  const original = await request.get(manifest.documents[0].download_url, { headers })
  expect((await original.body()).toString()).toBe(source)

  await navigate(page, '候选生成')
  await page.locator('.generation-header').getByRole('button', { name: /添加生成模型/ }).click()
  await page.getByLabel('Configuration Name（配置名称）').fill('E2E Model')
  await page.getByLabel('OpenAI-Compatible API URL（OpenAI 兼容 API 地址）').fill('http://127.0.0.1:18002/v1')
  await page.getByLabel('Model ID（模型标识）').fill('fixture-model')
  await page.getByRole('button', { name: /保存模型/ }).click()
  await page.getByLabel('Target Case Count（目标条数）').fill('2')
  await page.getByRole('button', { name: /开始生成/ }).click()
  await expect(page.locator('.generation-count')).toContainText('Candidates（候选） 1/2', { timeout: 30_000 })
  await expect(page.getByRole('status')).toContainText('Not enough chunks in the collection for a multi-chunk question（集合中没有足够的切块组成多切块题目）')
  const firstCandidate = page.locator('.generation-candidate').filter({ hasText: 'When did Acme launch?' })
  await firstCandidate.getByRole('button', { name: /审核/ }).click()
  await firstCandidate.getByRole('button', { name: /批准/ }).click()
  await expect(firstCandidate.locator('.review-status')).toHaveText('Approved（已批准）')
  const publish = page.getByRole('region', { name: /发布候选/ })
  await publish.getByRole('checkbox', { name: 'When did Acme launch?' }).check()
  await publish.getByLabel('Dataset Name（数据集名称）').fill('E2E Gold')
  await publish.getByRole('button', { name: /发布为数据集版本/ }).click()
  await expect(publish.getByRole('status')).toContainText('Published（已发布） v1')

  await page.getByLabel('Target Case Count（目标条数）').fill('1')
  await page.locator('.generation-form input[type=range]').press('Home')
  await page.getByLabel('Additional Requirements（补充要求）').fill('alternate')
  await page.getByRole('button', { name: /开始生成/ }).click()
  const secondCandidate = page.locator('.generation-candidate').filter({ hasText: 'Give the year recorded for this event.' })
  await expect(secondCandidate).toBeVisible({ timeout: 30_000 })
  await secondCandidate.getByRole('button', { name: /审核/ }).click()
  await secondCandidate.getByRole('button', { name: /批准/ }).click()
  await expect(secondCandidate.locator('.duplicate-verdict')).toContainText('Suspected Duplicate（疑似重复） · Awaiting Decision（待确认）')
  await secondCandidate.getByLabel('Reason for Duplicate Override（非重复放行理由）').fill('Different wording tests a distinct question.')
  await secondCandidate.getByRole('button', { name: /确认放行/ }).click()
  await expect(secondCandidate.locator('.duplicate-verdict')).toContainText('Suspected Duplicate（疑似重复） · Override Approved（已放行）')

  const datasetResponse = await request.get('/api/v1/datasets')
  const dataset = (await datasetResponse.json() as Array<{ id: string; name: string }>).find((item) => item.name === 'E2E Gold')!
  const versionResponse = await request.get(`/api/v1/datasets/${dataset.id}/versions/1`)
  const version = await versionResponse.json() as { cases: Array<{ case_id: string }> }
  const caseId = version.cases[0].case_id

  await navigate(page, 'HTTP 目标')
  for (const [name, protocol] of [['E2E JSON', 'json'], ['E2E SSE', 'sse']] as const) {
    const create = page.locator('.target-create')
    await create.getByLabel('Name（名称）').fill(name)
    await create.getByLabel('Endpoint URL（接口 URL）').fill(`http://127.0.0.1:18002/rag/${protocol}`)
    await create.getByLabel('Response Protocol（响应协议）').selectOption(protocol)
    await create.getByRole('button', { name: /保存/ }).click()
    await expect(page.locator('.target-layout .dataset-toolbar')).toContainText(name)
    const probe = page.locator('.target-probe')
    await probe.getByLabel('Question（问题）').fill('When did Acme launch?')
    await probe.getByRole('button', { name: /测试/ }).click()
    await expect(probe.getByRole('status')).toContainText('连接成功')
    await page.getByRole('button', { name: /采集预测/ }).click()
    await expect(page.locator('.target-job-detail .section-heading')).toContainText('Succeeded（成功） 1', { timeout: 30_000 })
  }

  await navigate(page, '预测批次')
  await page.getByRole('button', { name: /导入预测/ }).click()
  const prediction = page.getByRole('dialog', { name: /导入预测/ })
  await prediction.locator('input[type=file]').setInputFiles({
    name: 'e2e-predictions.jsonl', mimeType: 'application/json',
    buffer: Buffer.from(`${JSON.stringify({ case_id: caseId, answer: '2018', contexts: [{ document_id: 'doc-a', text: source }] })}\n`),
  })
  await prediction.getByRole('button', { name: 'Import（导入）' }).click()
  await expect(page.locator('.batch-counts')).toContainText('Match（匹配） 1')

  await navigate(page, '评价场景')
  await page.getByLabel('Model Name（模型名称）').fill('E2E Judge')
  await page.getByLabel('OpenAI-Compatible API URL（OpenAI 兼容 API 地址）').fill('http://127.0.0.1:18002/v1')
  await page.getByRole('button', { name: /保存模型/ }).click()
  await page.getByLabel('Scenario Name（场景名称）').fill('E2E Criteria')
  await page.getByLabel('Faithfulness（忠实度） · Evaluation Criteria（评价标准）').fill('Use the supplied context.')
  await page.getByLabel('Relevance（相关性） · Evaluation Criteria（评价标准）').fill('Answer the question.')
  await page.getByLabel('Correctness（正确性） · Evaluation Criteria（评价标准）').fill('Match the reference answer.')
  await page.getByRole('button', { name: /创建场景/ }).click()
  await expect(page.locator('.scenario-list')).toContainText('E2E Criteria')

  await navigate(page, '评测运行')
  await page.getByLabel('Evaluation Mode（评测模式）').selectOption('answer')
  await page.getByRole('button', { name: /运行评测/ }).click()
  const runDetail = page.getByRole('region', { name: /运行详情/ })
  await expect(runDetail.locator('.dataset-toolbar')).toContainText('Completed（已完成） · 1/1 cases（题）', { timeout: 30_000 })
  await expect(runDetail.locator('.run-summary')).toContainText('Succeeded（成功） 1')
  await expect(runDetail.locator('.run-case-row')).toContainText(caseId)
  const downloadEvent = page.waitForEvent('download')
  await runDetail.getByRole('link', { name: /JSON.*Export（导出）/ }).click()
  const exported = await downloadEvent
  expect((await readFile(await exported.path())).toString()).toContain(caseId)
  await runDetail.getByRole('button', { name: /复评/ }).click()
  await page.getByRole('button', { name: /重新评分/ }).click()
  await expect(runDetail.locator('.dataset-toolbar')).toContainText('Completed（已完成） · 1/1 cases（题）', { timeout: 30_000 })
  await expect(runDetail.locator('.run-summary')).toContainText('Succeeded（成功） 1')
})
