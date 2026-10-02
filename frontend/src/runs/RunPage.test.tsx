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
        cases: [{ case_id: 'q1', status: 'success', error: null }, { case_id: 'q2', status: 'pending', error: null }],
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
    expect(within(detail).getByText('待处理')).toBeTruthy()
    await userEvent.setup().click(within(detail).getByRole('button', { name: '取消' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/runs/run-1/cancel', { method: 'POST' }))
  })
})
