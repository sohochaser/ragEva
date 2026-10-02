// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PredictionPage } from './PredictionPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('PredictionPage', () => {
  it('shows saved batch counts and ordered contexts', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/datasets') return Promise.resolve(new Response(JSON.stringify([{
        id: 'd1', name: '客服集', latest_version: 1, latest_case_count: 2, version_count: 1, created_at: '2026-01-01',
      }])))
      if (url === '/api/v1/predictions') return Promise.resolve(new Response(JSON.stringify([{
        id: 'b1', dataset_id: 'd1', dataset_version: 1, evaluation_type: 'both', source_filename: 'predictions.jsonl',
        record_count: 1, matched_count: 1, missing_case_count: 1, created_at: '2026-01-01',
      }])))
      return Promise.resolve(new Response(JSON.stringify({
        id: 'b1', dataset_id: 'd1', dataset_version: 1, evaluation_type: 'both', source_filename: 'predictions.jsonl',
        record_count: 1, matched_count: 1, missing_case_count: 1, created_at: '2026-01-01', offset: 0, limit: 50,
        predictions: [{ case_id: 'q1', answer: '可以退款', latency_ms: null,
          contexts: [{ text: '先申请', document_id: 'doc-1', chunk_id: null, source: null }, { text: '后审核', document_id: 'doc-2', chunk_id: null, source: null }],
        }],
      })))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<PredictionPage />)

    const detail = await screen.findByRole('region', { name: /预测内容/ })
    expect(screen.getByText('Unmatched（未匹配） 1')).toBeTruthy()
    const chunks = within(detail).getAllByRole('listitem')
    expect(chunks.map((item) => item.textContent)).toEqual(['#1doc-1先申请', '#2doc-2后审核'])
  })

  it('keeps import dialog open with row-level backend errors', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/datasets' || url === '/api/v1/predictions') return Promise.resolve(new Response('[]'))
      return Promise.resolve(new Response(JSON.stringify({
        error: 'validation_failed', issues: [{ line: 3, field: 'contexts[0].document_id', code: 'missing_field', message: 'document_id 不能为空' }],
      }), { status: 422 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<PredictionPage />)
    await screen.findByText(/暂无预测批次/)
    await user.click(screen.getByRole('button', { name: /导入预测/ }))
    const dialog = screen.getByRole('dialog', { name: /导入预测/ })
    await user.type(within(dialog).getByRole('textbox', { name: /新数据集名称/ }), '新集')
    await user.upload(within(dialog).getByLabelText(/预测文件/), new File(['{}'], 'predictions.jsonl'))
    fireEvent.submit(dialog.querySelector('form')!)

    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('Line 3（第 3 行） · contexts[0].document_id'))
    expect(screen.getByRole('dialog', { name: /导入预测/ })).toBeTruthy()
  })
})
