// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TargetPage } from './TargetPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('TargetPage', () => {
  it('saves a target and starts a version-bound collection', async () => {
    const target = { id: 't1', name: 'Local RAG', url: 'http://127.0.0.1:9900/rag', has_token: true, timeout_seconds: 30, retries: 1, protocol: 'sse', created_at: '2026-01-01' }
    const job = { id: 'j1', target_id: 't1', dataset_id: 'd1', dataset_version: 1, evaluation_type: 'retrieval', status: 'queued', batch_id: null, total_count: 2, processed_count: 0, success_count: 0, failed_count: 0, created_at: '2026-01-01', started_at: null, finished_at: null }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/targets' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(target)))
      if (url === '/api/v1/targets') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/target-jobs' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(job)))
      if (url === '/api/v1/target-jobs') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/datasets') return Promise.resolve(new Response(JSON.stringify([{ id: 'd1', name: '客服集', latest_version: 1 }])))
      if (url === '/api/v1/datasets/d1/versions') return Promise.resolve(new Response(JSON.stringify([{ id: 'v1', version: 1 }])))
      if (url === '/api/v1/target-jobs/j1/cases') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/target-jobs/j1') return Promise.resolve(new Response(JSON.stringify(job)))
      return Promise.resolve(new Response('{}', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<TargetPage />)
    await screen.findByText(/暂无目标/)
    const form = screen.getByRole('button', { name: /保存/ }).closest('form')!
    await user.type(within(form).getByRole('textbox', { name: /名称/ }), 'Local RAG')
    await user.type(within(form).getByRole('textbox', { name: /接口 URL/ }), 'http://127.0.0.1:9900/rag')
    await user.type(within(form).getByLabelText(/Bearer Token/), 'private-token')
    await user.selectOptions(within(form).getByRole('combobox', { name: /响应协议/ }), 'sse')
    expect((within(form).getByRole('spinbutton', { name: 'Timeout (seconds)（超时，秒）' }) as HTMLInputElement).value).toBe('30')
    await user.click(within(form).getByRole('button', { name: /保存/ }))
    await screen.findByText('Bearer Configured（已配置 Bearer）')
    expect(screen.getByText('Timeout（超时） 30 seconds（秒）')).toBeTruthy()
    expect(within(form).getByLabelText(/Bearer Token/).getAttribute('value')).toBe('')
    const creation = fetchMock.mock.calls.find(([url, options]) => url === '/api/v1/targets' && options?.method === 'POST')
    expect(JSON.parse(String(creation?.[1]?.body)).bearer_token).toBe('private-token')
    expect(JSON.parse(String(creation?.[1]?.body)).protocol).toBe('sse')
    expect(JSON.parse(String(creation?.[1]?.body)).max_concurrency).toBe(4)
    expect(JSON.parse(String(creation?.[1]?.body)).timeout_seconds).toBe(30)

    await user.selectOptions(screen.getByRole('combobox', { name: /评测类型/ }), 'retrieval')
    await user.click(screen.getByRole('button', { name: /采集预测/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/target-jobs', expect.objectContaining({ method: 'POST' })))
    const submitted = fetchMock.mock.calls.find(([url, options]) => url === '/api/v1/target-jobs' && options?.method === 'POST')
    expect(JSON.parse(String(submitted?.[1]?.body))).toMatchObject({ target_id: 't1', dataset_id: 'd1', dataset_version: 1, evaluation_type: 'retrieval' })
  })

  it('shows the request budget and cancels collection', async () => {
    const target = { id: 't1', name: 'Local RAG', url: 'http://127.0.0.1:9900/rag', has_token: false, timeout_seconds: 30, retries: 1, max_concurrency: 4, protocol: 'json', created_at: '2026-01-01' }
    const job = { id: 'j1', target_id: 't1', dataset_id: 'd1', dataset_version: 1, evaluation_type: 'answer', status: 'running', batch_id: null, total_count: 2, processed_count: 0, success_count: 0, failed_count: 0, cancelled_count: 0, cancel_requested: false, estimated_external_calls: 4, created_at: '2026-01-01', started_at: '2026-01-01', finished_at: null }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/targets') return Promise.resolve(new Response(JSON.stringify([target])))
      if (url === '/api/v1/target-jobs') return Promise.resolve(new Response(JSON.stringify([job])))
      if (url === '/api/v1/datasets') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/target-jobs/j1/cases') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/target-jobs/j1/cancel' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify({ ...job, status: 'cancelled', cancelled_count: 2, cancel_requested: true })))
      if (url === '/api/v1/target-jobs/j1') return Promise.resolve(new Response(JSON.stringify(job)))
      return Promise.resolve(new Response('{}', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TargetPage />)
    await screen.findByText('Up to（预计最多） 4 requests（次请求）')
    await userEvent.setup().click(screen.getByRole('button', { name: /取消采集/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/target-jobs/j1/cancel', { method: 'POST' }))
  })
})
