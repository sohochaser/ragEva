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

describe('RunPage', () => {
  it('shows progress and cancels a running evaluation', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
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
      return Promise.resolve(new Response(JSON.stringify(run)))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<RunPage />)

    const detail = await screen.findByRole('region', { name: '运行详情' })
    await waitFor(() => expect(within(detail).getByText('运行中 · 1/2 题')).toBeTruthy())
    expect(within(detail).getByRole('button', { name: 'q2待处理' })).toBeTruthy()
    await userEvent.setup().click(within(detail).getByRole('button', { name: '取消' }))
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
      if (url === '/api/v1/predictions') return Promise.resolve(new Response(JSON.stringify([{ id: 'batch-1', source_filename: 'answers.jsonl', evaluation_type: 'retrieval', dataset_id: 'dataset-1', dataset_version: 1 }])))
      if (url === '/api/v1/runs') return Promise.resolve(new Response(JSON.stringify([completed])))
      if (url.includes('/cases?')) return Promise.resolve(new Response(JSON.stringify({ run_id: 'run-1', total: 1, offset: 0, limit: 100, cases: [{ case_id: 'q1', status: 'success', question: '退款?', answer: '可退', reference_answer: '可退', contexts: [{ text: '七天可退', document_id: 'doc-1', chunk_id: null, source: null }], reference_chunks: [{ text: '七天可退', document_id: 'doc-1' }], score, error: null, target_latency_ms: 20, elapsed_ms: 2 }] })))
      return Promise.resolve(new Response(JSON.stringify(completed)))
    }))
    render(<RunPage />)
    const detail = await screen.findByRole('region', { name: '运行详情' })
    await waitFor(() => expect(within(detail).getByRole('region', { name: '总体指标' })).toBeTruthy())
    expect(within(detail).getByText('0.100')).toBeTruthy()
    expect(within(detail).getAllByText('七天可退')).toHaveLength(2)
    expect(within(detail).getByRole('region', { name: '匹配证据' }).textContent).toContain('0.980')
    expect(within(detail).getByRole('link', { name: 'CSV' }).getAttribute('href')).toContain('format=csv')
    expect(within(detail).getByRole('link', { name: 'JSON' }).getAttribute('href')).toContain('format=json')
  })
})
