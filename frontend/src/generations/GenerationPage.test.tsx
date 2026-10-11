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
    if (url === '/api/v1/document-collections/collection-1/questions') return Promise.resolve(new Response(JSON.stringify([candidate])))
    if (url === '/api/v1/generations/run-1/candidates') return Promise.resolve(new Response(JSON.stringify([candidate])))
    if (url === '/api/v1/generations/run-1/usage') return Promise.resolve(new Response(JSON.stringify({
      call_count: 1,
      totals: {
        input: { actual: { calls: 0, tokens: 0 }, estimated: { calls: 1, tokens: 24 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 0, tokens: 0 } },
        output: { actual: { calls: 0, tokens: 0 }, estimated: { calls: 0, tokens: 0 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 1, tokens: 0 } },
      },
      calls: [{ id: 'usage-1', owner_type: 'generation', owner_id: 'run-1', operation: 'generation', case_id: '2', model_id: 'generator-v1', input_tokens: 24, input_source: 'estimated', output_tokens: null, output_source: 'unknown', tokenizer: 'bytelevel-v1', created_at: '2026-10-02' }],
    })))
    if (url === '/api/v1/datasets') return Promise.resolve(new Response('[]'))
    return Promise.reject(new Error(`Unexpected URL ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  const user = userEvent.setup()
  render(<GenerationPage />)
  await screen.findByRole('option', { name: /产品知识 · Chunk Manifest（chunk 清单）/ })
  await user.click(screen.getByRole('button', { name: /添加生成模型/ }))
  await user.type(screen.getByRole('textbox', { name: /配置名称/ }), '专用生成模型')
  await user.type(screen.getByRole('textbox', { name: /OpenAI 兼容 API 地址/ }), 'https://model.test/v1')
  await user.type(screen.getByRole('textbox', { name: /模型标识/ }), 'generator-v1')
  await user.type(screen.getByLabelText(/Bearer Token/), 'private-token')
  await user.click(screen.getByRole('button', { name: /保存模型/ }))
  await waitFor(() => expect(screen.getAllByRole('option', { name: /专用生成模型 · generator-v1/ })).toHaveLength(2))
  await user.click(screen.getByText(/从已有集合生成/))
  await user.clear(screen.getByRole('spinbutton', { name: /目标条数/ }))
  await user.type(screen.getByRole('spinbutton', { name: /目标条数/ }), '3')
  expect(screen.getByText('Multi-Chunk Ratio（多切块比例） · 30%（百分比）')).toBeTruthy()
  await user.selectOptions(screen.getByRole('combobox', { name: /并发调用/ }), '2')
  await user.click(screen.getByRole('button', { name: /开始生成/ }))
  await screen.findByRole('heading', { name: /产品支持什么？/ })
  const request = fetchMock.mock.calls.find(([url]) => url === '/api/v1/document-collections/collection-1/generations')
  expect(JSON.parse(request![1]!.body as string)).toMatchObject({
    model_id: 'model-2', target_count: 3, multi_chunk_ratio: 0.3, max_concurrency: 2,
  })
  expect(screen.getByText('Candidates（候选） 1/3 · Multi-Chunk（多切块） 0/2')).toBeTruthy()
  expect(screen.getByText(/已达到模型调用上限/)).toBeTruthy()
  expect(screen.getAllByText(/产品支持离线检索。/).length).toBeGreaterThan(0)
  expect(screen.getAllByText('doc-1').length).toBeGreaterThan(0)
  expect(screen.getByRole('region', { name: /模型 token 用量/ }).textContent).toContain('Estimated（估算） 24 tokens（词元）')
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
  await user.click(screen.getByText(/从已有集合生成/))
  await screen.findByText(/暂无文档集合/)
  expect(screen.getByText(/暂无生成模型/)).toBeTruthy()
  expect(screen.getByRole('button', { name: /开始生成/ }).hasAttribute('disabled')).toBe(true)
  await user.click(screen.getByRole('button', { name: /打开文档集合/ }))
  expect(openCollections).toHaveBeenCalledOnce()
})

it('uploads documents, retries generation without reuploading, and lists collection questions', async () => {
  const collection = { id: 'collection-new', name: '上传资料', source_kind: 'source_files', document_count: 1, chunk_size: 1000, chunk_overlap: 100, created_at: '2026-10-12' }
  const model = { id: 'model-1', name: '生成模型', model_name: 'generator-v1', base_url: 'https://model.test/v1', timeout_seconds: 30, has_token: true, created_at: '2026-10-12' }
  const run = {
    id: 'run-new', collection_id: collection.id, status: 'completed', config: { prompt_version: 'candidate-generation-v2' },
    target_count: 1, target_multi_count: 0, actual_count: 1, actual_multi_count: 0,
    attempted_count: 1, max_calls: 3, max_concurrency: 4, shortfall_reasons: [], attempt_errors: {},
    created_at: '2026-10-12', started_at: '2026-10-12', finished_at: '2026-10-12',
  }
  const candidate = {
    id: 'candidate-new', run_id: run.id, collection_id: collection.id, source_document_id: 'notes-1',
    slot_index: 0, question: '发布日期是什么？', reference_answer: '2018 年。',
    reference_chunks: [{ document_id: 'notes-1', text: '2018 年发布' }], support_positions: [0],
    multi_chunk: false, status: 'pending_review', prompt_version: 'candidate-generation-v2', model_name: 'generator-v1', created_at: '2026-10-12',
  }
  let starts = 0
  const fetchMock = vi.fn((url: string, options?: RequestInit) => {
    if (url === '/api/v1/document-collections' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(collection), { status: 201 }))
    if (url === '/api/v1/document-collections') return Promise.resolve(new Response('[]'))
    if (url === '/api/v1/online-models') return Promise.resolve(new Response(JSON.stringify([model])))
    if (url === '/api/v1/generations') return Promise.resolve(new Response('[]'))
    if (url === '/api/v1/document-collections/collection-new/generations') {
      starts += 1
      return Promise.resolve(starts === 1 ? new Response('Unavailable', { status: 503 }) : new Response(JSON.stringify(run), { status: 202 }))
    }
    if (url === '/api/v1/document-collections/collection-new/questions') return Promise.resolve(new Response(JSON.stringify(starts > 1 ? [candidate] : [])))
    if (url === '/api/v1/generations/run-new/candidates') return Promise.resolve(new Response(JSON.stringify([candidate])))
    if (url === '/api/v1/generations/run-new/usage') return Promise.resolve(new Response(JSON.stringify({ call_count: 0, totals: { input: {}, output: {} }, calls: [] })))
    if (url === '/api/v1/datasets') return Promise.resolve(new Response('[]'))
    return Promise.reject(new Error(`Unexpected URL ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  const user = userEvent.setup()
  render(<GenerationPage />)
  await waitFor(() => expect(screen.getAllByRole('option', { name: /生成模型 · generator-v1/ })).toHaveLength(2))
  const fileInput = screen.getByLabelText(/来源文档/) as HTMLInputElement
  await user.upload(fileInput, new File(['2018 年发布'], 'notes.txt', { type: 'text/plain' }))
  await user.clear(screen.getByRole('textbox', { name: /集合名称/ }))
  await user.type(screen.getByRole('textbox', { name: /集合名称/ }), '上传资料')
  await user.clear(screen.getByRole('spinbutton', { name: /题目数量/ }))
  await user.type(screen.getByRole('spinbutton', { name: /题目数量/ }), '1')
  await waitFor(() => expect((screen.getByRole('button', { name: /上传并生成/ }) as HTMLButtonElement).disabled).toBe(false))
  expect(fileInput.files).toHaveLength(1)
  expect((document.querySelector('.quick-generation-form') as HTMLFormElement).checkValidity()).toBe(true)
  await user.click(screen.getByRole('button', { name: /上传并生成/ }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url, options]) => url === '/api/v1/document-collections' && options?.method === 'POST')).toHaveLength(1))
  await screen.findByText(/文档已保存，等待生成/)
  await user.click(screen.getByRole('button', { name: /重试生成/ }))
  await screen.findByRole('heading', { name: '发布日期是什么？' })
  expect(fetchMock.mock.calls.filter(([url, options]) => url === '/api/v1/document-collections' && options?.method === 'POST')).toHaveLength(1)
  expect(screen.getByRole('region', { name: /集合问题/ }).textContent).toContain('2018 年发布')
  expect(screen.getByRole('region', { name: /集合问题/ }).textContent).toContain('notes-1')
})
