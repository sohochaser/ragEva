// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RunPage } from './RunPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const run = {
  id: 'run-1', prediction_batch_id: 'batch-1', dataset_id: 'dataset-1', dataset_version: 1,
  status: 'running', config: {}, model_id: 'model-1', aggregate: null, cancel_requested: false,
  total_count: 2, processed_count: 1, success_count: 1, failed_count: 0,
  not_applicable_count: 0, cancelled_count: 0, created_at: '2026-01-01',
  started_at: '2026-01-01', finished_at: null,
}
const usage = {
  call_count: 1,
  totals: {
    input: { actual: { calls: 1, tokens: 12 }, estimated: { calls: 0, tokens: 0 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 0, tokens: 0 } },
    output: { actual: { calls: 1, tokens: 4 }, estimated: { calls: 0, tokens: 0 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 0, tokens: 0 } },
  },
  calls: [{ id: 'usage-1', owner_type: 'run', owner_id: 'run-1', operation: 'answer_scoring', case_id: 'q1:relevance', model_id: 'judge', input_tokens: 12, input_source: 'actual', output_tokens: 4, output_source: 'actual', tokenizer: null, created_at: '2026-01-01' }],
}

describe('RunPage', () => {
  it('shows progress and cancels a running evaluation', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/scenarios' || url === '/api/v1/online-models') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/predictions') return Promise.resolve(new Response(JSON.stringify([{
        id: 'batch-1', source_filename: 'answers.jsonl', evaluation_type: 'retrieval',
        dataset_id: 'dataset-1', dataset_version: 1,
      }])))
      if (url === '/api/v1/runs' && !options) return Promise.resolve(new Response(JSON.stringify([run])))
      if (url === '/api/v1/runs/run-1/cases') throw new Error('missing query')
      if (url.startsWith('/api/v1/runs/run-1/cases?')) return Promise.resolve(new Response(JSON.stringify({
        run_id: 'run-1', total: 2, offset: 0, limit: 100,
        cases: [
          { case_id: 'q1', status: 'success', question: 'Q1', answer: null, reference_answer: null, contexts: null, reference_chunks: null, score: null, error: null, target_latency_ms: null, elapsed_ms: 2 },
          { case_id: 'q2', status: 'pending', question: 'Q2', answer: null, reference_answer: null, contexts: null, reference_chunks: null, score: null, error: null, target_latency_ms: null, elapsed_ms: null },
        ],
      })))
      if (url === '/api/v1/runs/run-1/cancel') return Promise.resolve(new Response(JSON.stringify({
        ...run, status: 'cancelled', cancel_requested: true, processed_count: 2, cancelled_count: 1,
      })))
      if (url === '/api/v1/runs/run-1/usage') return Promise.resolve(new Response(JSON.stringify(usage)))
      return Promise.resolve(new Response(JSON.stringify(run)))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<RunPage />)

    const detail = await screen.findByRole('region', { name: /运行详情/ })
    await waitFor(() => expect(within(detail).getByText('Running（运行中） · 1/2 cases（题）')).toBeTruthy())
    expect(within(detail).getByRole('button', { name: /q2.*Pending（待处理）/ })).toBeTruthy()
    await userEvent.setup().click(within(detail).getByRole('button', { name: /取消/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/runs/run-1/cancel', { method: 'POST' }))
  })

  it('shows aggregate and evidence and offers both export formats', async () => {
    const score = { model_id: 'local:hash', threshold: 0.8, match_rule_version: 'one-to-one-v1', gain_rule_version: 'ordered-linear-v1', scores: {
      10: { k: 10, precision: 0.1, ap: 1, ndcg: 1, matches: [{ predicted_index: 0, reference_index: 0, similarity: 0.98 }], decisions: [{ predicted_index: 0, reference_index: 0, similarity: 0.98, candidate: true, selected: true, reason: 'matched' }] },
      20: { k: 20, precision: 0.05, ap: 1, ndcg: 1, matches: [{ predicted_index: 0, reference_index: 0, similarity: 0.98 }], decisions: [{ predicted_index: 0, reference_index: 0, similarity: 0.98, candidate: true, selected: true, reason: 'matched' }] },
    } }
    const completed = { ...run, status: 'completed', processed_count: 1, total_count: 1, finished_at: '2026-01-01', config: { metrics: ['precision', 'map', 'ndcg'] }, aggregate: {
      valid_count: 1, not_applicable_count: 0, precision_at_k: { 10: 0.1, 20: 0.05 }, map_at_k: { 10: 1, 20: 1 }, ndcg_at_k: { 10: 1, 20: 1 },
      distribution: { precision: { 10: [1, 0, 0, 0, 0], 20: [1, 0, 0, 0, 0] }, map: { 10: [0, 0, 0, 0, 1], 20: [0, 0, 0, 0, 1] }, ndcg: { 10: [0, 0, 0, 0, 1], 20: [0, 0, 0, 0, 1] } },
    } }
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/v1/scenarios' || url === '/api/v1/online-models') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/predictions') return Promise.resolve(new Response(JSON.stringify([{ id: 'batch-1', source_filename: 'answers.jsonl', evaluation_type: 'retrieval', dataset_id: 'dataset-1', dataset_version: 1 }])))
      if (url === '/api/v1/runs') return Promise.resolve(new Response(JSON.stringify([completed])))
      if (url.includes('/cases?')) return Promise.resolve(new Response(JSON.stringify({ run_id: 'run-1', total: 1, offset: 0, limit: 100, cases: [{ case_id: 'q1', status: 'success', question: '退款?', answer: '可退', reference_answer: '可退', contexts: [{ text: '七天可退', document_id: 'doc-1', chunk_id: null, source: null }], reference_chunks: [{ text: '七天可退', document_id: 'doc-1' }], score, error: null, target_latency_ms: 20, elapsed_ms: 2 }] })))
      if (url === '/api/v1/runs/run-1/usage') return Promise.resolve(new Response(JSON.stringify(usage)))
      return Promise.resolve(new Response(JSON.stringify(completed)))
    }))
    render(<RunPage />)
    const detail = await screen.findByRole('region', { name: /运行详情/ })
    await waitFor(() => expect(within(detail).getByRole('region', { name: /总体指标/ })).toBeTruthy())
    expect(within(detail).getByText('0.100')).toBeTruthy()
    expect(within(detail).getByRole('region', { name: /模型 token 用量/ }).textContent).toContain('Actual（实际） 12 tokens（词元）')
    expect(within(detail).getAllByText('七天可退')).toHaveLength(2)
    expect(within(detail).getByRole('region', { name: /匹配证据/ }).textContent).toContain('0.980')
    expect(within(detail).getByRole('link', { name: /CSV.*Export（导出）/ }).getAttribute('href')).toContain('format=csv')
    expect(within(detail).getByRole('link', { name: /JSON.*Export（导出）/ }).getAttribute('href')).toContain('format=json')
  })

  it('starts answer evaluation with a scenario version and shows metric evidence', async () => {
    const scenario = { id: 'sv2', scenario_id: 's1', name: '客服', version: 2, faithfulness: '证据', relevance: '问题', correctness: '答案', prompt_version: 'answer-eval-v1', created_at: '2026-01-01' }
    const model = { id: 'm1', name: 'Judge', model_name: 'judge', base_url: 'https://model.example/v1', has_token: true, timeout_seconds: 60, created_at: '2026-01-01' }
    const answerRun = { ...run, status: 'completed', config: { mode: 'answer', answer: { scenario_id: 's1', scenario_version: 2 } }, aggregate: { valid_count: 0, not_applicable_count: 0, precision_at_k: { 10: null, 20: null }, map_at_k: { 10: null, 20: null }, ndcg_at_k: { 10: null, 20: null }, answer_metrics: { relevance: { valid_count: 1, failed_count: 0, not_applicable_count: 0, mean_score: 0.7 } } }, total_count: 1, processed_count: 1 }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/predictions') return Promise.resolve(new Response(JSON.stringify([{ id: 'batch-1', source_filename: 'answer.jsonl', evaluation_type: 'answer', dataset_id: 'dataset-1', dataset_version: 1 }])))
      if (url === '/api/v1/scenarios') return Promise.resolve(new Response(JSON.stringify([scenario])))
      if (url === '/api/v1/scenarios/s1/versions') return Promise.resolve(new Response(JSON.stringify([scenario])))
      if (url === '/api/v1/online-models') return Promise.resolve(new Response(JSON.stringify([model])))
      if (url === '/api/v1/runs' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(answerRun)))
      if (url === '/api/v1/runs') return Promise.resolve(new Response('[]'))
      if (url.includes('/cases?')) return Promise.resolve(new Response(JSON.stringify({ run_id: 'run-1', total: 1, offset: 0, limit: 100, cases: [{ case_id: 'q1', status: 'success', question: '退款?', answer: '可退', reference_answer: '可退', contexts: null, reference_chunks: null, score: null, error: null, target_latency_ms: null, elapsed_ms: 20, answer_metrics: { relevance: { status: 'success', score: 0.7, reason: '回答了问题', raw_response: '{"score":0.7,"reason":"回答了问题"}', error: null, usage: { input_tokens: 12, output_tokens: 4 }, model_name: 'judge', prompt_version: 'answer-eval-v1', criteria: '问题' } } }] })))
      if (url === '/api/v1/runs/run-1/usage') return Promise.resolve(new Response(JSON.stringify(usage)))
      return Promise.resolve(new Response(JSON.stringify(answerRun)))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<RunPage />)
    await screen.findByRole('combobox', { name: /评测模式/ })
    await user.selectOptions(screen.getByRole('combobox', { name: /评测模式/ }), 'answer')
    await screen.findByRole('combobox', { name: /场景版本/ })
    await user.click(screen.getByRole('button', { name: /运行评测/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/runs', expect.objectContaining({ method: 'POST' })))
    const submitted = fetchMock.mock.calls.find(([url, options]) => url === '/api/v1/runs' && options?.method === 'POST')
    expect(JSON.parse(String(submitted?.[1]?.body))).toMatchObject({ mode: 'answer', scenario_id: 's1', scenario_version: 2, judge_model_id: 'm1' })
    expect((await screen.findByRole('region', { name: /回答评分/ })).textContent).toContain('回答了问题')
    expect(screen.getByRole('region', { name: /总体指标/ }).textContent).toContain('0.700')
  })

  it('rescores a saved run with its prediction batch and edited threshold', async () => {
    const source = { ...run, status: 'completed', total_count: 1, processed_count: 1,
      config: { mode: 'retrieval', model_name: 'fake-v1', model_path: null, offline: true,
        threshold: 0.8, metrics: ['map'], match_rule_version: 'one-to-one-v1', gain_rule_version: 'ordered-linear-v1' } }
    const rescored = { ...source, id: 'run-2', status: 'queued', processed_count: 0,
      config: { ...source.config, threshold: 0.9, rescore_of_run_id: 'run-1' } }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/scenarios' || url === '/api/v1/online-models') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/predictions') return Promise.resolve(new Response(JSON.stringify([{ id: 'batch-1', source_filename: 'pred.jsonl', evaluation_type: 'retrieval', dataset_id: 'dataset-1', dataset_version: 1 }])))
      if (url === '/api/v1/runs') return Promise.resolve(new Response(JSON.stringify([source])))
      if (url === '/api/v1/runs/run-1/rescore' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(rescored)))
      if (url.includes('/cases?')) return Promise.resolve(new Response(JSON.stringify({ run_id: url.includes('run-2') ? 'run-2' : 'run-1', total: 0, offset: 0, limit: 100, cases: [] })))
      if (url === '/api/v1/runs/run-1/usage' || url === '/api/v1/runs/run-2/usage') return Promise.resolve(new Response(JSON.stringify(usage)))
      if (url === '/api/v1/runs/run-2') return Promise.resolve(new Response(JSON.stringify(rescored)))
      return Promise.resolve(new Response(JSON.stringify(source)))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<RunPage />)
    const detail = await screen.findByRole('region', { name: /运行详情/ })
    await user.click(await within(detail).findByRole('button', { name: /复评/ }))
    expect(screen.getByRole('combobox', { name: /预测批次/ }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('Rescore Run（复评运行） run-1')).toBeTruthy()
    const threshold = screen.getByRole('spinbutton', { name: /相似度阈值/ })
    await user.clear(threshold)
    await user.type(threshold, '0.9')
    await user.click(screen.getByRole('button', { name: /重新评分/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/runs/run-1/rescore', expect.objectContaining({ method: 'POST' })))
    const submitted = fetchMock.mock.calls.find(([url]) => url === '/api/v1/runs/run-1/rescore')
    const payload = JSON.parse(String(submitted?.[1]?.body))
    expect(payload.threshold).toBe(0.9)
    expect(payload).not.toHaveProperty('prediction_batch_id')
    expect((await screen.findByRole('button', { name: /Source Run（源运行） run-1/ })).textContent).toContain('run-1')
  })
})
