// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { GenerationPage } from './GenerationPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('creates a generation and shows partial candidates with source evidence', async () => {
  const collection = { id: 'collection-1', name: '产品知识', source_kind: 'chunks_only', document_count: 1, chunk_size: 0, chunk_overlap: 0, created_at: '2026-10-02' }
  const model = { id: 'model-1', name: '生成模型', model_name: 'generator-v1', base_url: 'https://model.test/v1', timeout_seconds: 30, has_token: true, created_at: '2026-10-02' }
  const newModel = { ...model, id: 'model-2', name: '专用生成模型' }
  const run = {
    id: 'run-1', collection_id: collection.id, status: 'partial', config: { prompt_version: 'candidate-generation-v1' },
    target_count: 3, target_multi_count: 2, actual_count: 1, actual_multi_count: 0,
    attempted_count: 3, max_calls: 3, max_concurrency: 2,
    shortfall_reasons: ['call_limit_reached', 'model_or_validation_errors'],
    attempt_errors: { invalid_model_response: 2 }, created_at: '2026-10-02', started_at: '2026-10-02', finished_at: '2026-10-02',
  }
  const candidate = {
    id: 'candidate-1', run_id: 'run-1', slot_index: 2, question: '产品支持什么？',
    reference_answer: '支持离线检索。', reference_chunks: [{ document_id: 'doc-1', text: '产品支持离线检索。' }],
    support_positions: [0], multi_chunk: false, status: 'pending_review',
    prompt_version: 'candidate-generation-v1', model_name: 'generator-v1', created_at: '2026-10-02',
  }
  const fetchMock = vi.fn((url: string, options?: RequestInit) => {
    if (url === '/api/v1/document-collections') return Promise.resolve(new Response(JSON.stringify([collection])))
    if (url === '/api/v1/online-models' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(newModel), { status: 201 }))
    if (url === '/api/v1/online-models') return Promise.resolve(new Response(JSON.stringify([model])))
    if (url === '/api/v1/generations') return Promise.resolve(new Response('[]'))
    if (url === '/api/v1/document-collections/collection-1/generations' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(run), { status: 202 }))
    if (url === '/api/v1/generations/run-1/candidates') return Promise.resolve(new Response(JSON.stringify([candidate])))
    if (url === '/api/v1/generations/run-1/usage') return Promise.resolve(new Response(JSON.stringify({
      call_count: 1,
      totals: {
        input: { actual: { calls: 0, tokens: 0 }, estimated: { calls: 1, tokens: 24 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 0, tokens: 0 } },
        output: { actual: { calls: 0, tokens: 0 }, estimated: { calls: 0, tokens: 0 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 1, tokens: 0 } },
      },
      calls: [{ id: 'usage-1', owner_type: 'generation', owner_id: 'run-1', operation: 'generation', case_id: '2', model_id: 'generator-v1', input_tokens: 24, input_source: 'estimated', output_tokens: null, output_source: 'unknown', tokenizer: 'bytelevel-v1', created_at: '2026-10-02' }],
    })))
    return Promise.reject(new Error(`Unexpected URL ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  const user = userEvent.setup()
  render(<GenerationPage />)
  await screen.findByRole('option', { name: '产品知识 · chunk 清单' })
  await user.click(screen.getByRole('button', { name: '添加生成模型' }))
  await user.type(screen.getByRole('textbox', { name: '配置名称' }), '专用生成模型')
  await user.type(screen.getByRole('textbox', { name: 'OpenAI 兼容 API 地址' }), 'https://model.test/v1')
  await user.type(screen.getByRole('textbox', { name: '模型标识' }), 'generator-v1')
  await user.type(screen.getByLabelText('Bearer Token'), 'private-token')
  await user.click(screen.getByRole('button', { name: '保存模型' }))
  await screen.findByRole('option', { name: '专用生成模型 · generator-v1' })
  await user.clear(screen.getByRole('spinbutton', { name: '目标条数' }))
  await user.type(screen.getByRole('spinbutton', { name: '目标条数' }), '3')
  await user.selectOptions(screen.getByRole('combobox', { name: '并发调用' }), '2')
  await user.click(screen.getByRole('button', { name: '开始生成' }))
  await screen.findByText('产品支持什么？')
  const request = fetchMock.mock.calls.find(([url]) => url === '/api/v1/document-collections/collection-1/generations')
  expect(JSON.parse(request![1]!.body as string)).toMatchObject({
    model_id: 'model-2', target_count: 3, multi_chunk_ratio: 0.3, max_concurrency: 2,
  })
  expect(screen.getByText('候选 1/3 · 多 chunk 0/2')).toBeTruthy()
  expect(screen.getByText('已达到模型调用上限')).toBeTruthy()
  expect(screen.getByText('产品支持离线检索。')).toBeTruthy()
  expect(screen.getByText('doc-1')).toBeTruthy()
  expect(screen.getByRole('region', { name: '模型 token 用量' }).textContent).toContain('估算 24')
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
})

it('points to missing inputs before a generation can start', async () => {
  const openCollections = vi.fn()
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (['/api/v1/document-collections', '/api/v1/online-models', '/api/v1/generations'].includes(url)) {
      return Promise.resolve(new Response('[]'))
    }
    return Promise.reject(new Error(`Unexpected URL ${url}`))
  }))
  const user = userEvent.setup()
  render(<GenerationPage onOpenCollections={openCollections} />)
  await screen.findByText('暂无文档集合')
  expect(screen.getByText('暂无生成模型')).toBeTruthy()
  expect(screen.getByRole('button', { name: '开始生成' }).hasAttribute('disabled')).toBe(true)
  await user.click(screen.getByRole('button', { name: '打开文档集合' }))
  expect(openCollections).toHaveBeenCalledOnce()
})
