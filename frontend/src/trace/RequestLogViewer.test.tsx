// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RequestLogViewer } from './RequestLogViewer'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('RequestLogViewer', () => {
  it('filters failed requests and shows the cross-process error timeline', async () => {
    const failedId = 'a'.repeat(32)
    const goodId = 'b'.repeat(32)
    const requests = [
      { request_id: failedId, started_at: '2026-10-04T02:00:00Z', method: 'POST', route: '/api/v1/runs', http_status: 202, status: 'failed', error_code: null },
      { request_id: goodId, started_at: '2026-10-04T01:00:00Z', method: 'GET', route: '/api/v1/runs', http_status: 200, status: 'success', error_code: null },
    ]
    const detail = { ...requests[0], spans: [
      { span_id: '1', parent_span_id: null, name: 'http.request', started_at: requests[0].started_at, duration_ms: 10, status: 'success', error_code: null, error_detail: null, attributes: { 'http.method': 'POST' } },
      { span_id: '2', parent_span_id: '1', name: 'run.worker', started_at: requests[0].started_at, duration_ms: 20, status: 'failed', error_code: 'model_error', error_detail: '模型调用失败', attributes: { 'run.id': 'run-1' } },
    ] }
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url.endsWith(failedId) ? detail : requests }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<RequestLogViewer />)

    expect(await screen.findByText(goodId)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Errors（错误）' }))
    expect(screen.queryByText(goodId)).toBeNull()
    await user.click(screen.getByRole('button', { name: new RegExp(failedId) }))
    const timeline = screen.getByRole('list')
    expect(within(timeline).getByText('run.worker')).toBeTruthy()
    expect(within(timeline).getByText(/model_error/)).toBeTruthy()
    expect(within(timeline).getByText(/模型调用失败/)).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/request-logs/${failedId}`, { cache: 'no-store' })
  })

  it('looks up a request ID and reports missing logs', async () => {
    const requestId = 'c'.repeat(32)
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith(requestId)
      ? { ok: false, status: 404, json: async () => ({ detail: '请求日志不存在' }) }
      : { ok: true, json: async () => [] }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<RequestLogViewer />)
    await user.type(screen.getByLabelText('Request ID（请求 ID）'), requestId)
    await user.click(screen.getByRole('button', { name: 'Find（查找）' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', '请求日志不存在')
  })
})
