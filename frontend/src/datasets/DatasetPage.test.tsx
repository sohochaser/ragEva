// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DatasetPage } from './DatasetPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('DatasetPage', () => {
  it('shows ordered reference chunks for a versioned case', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/datasets') return Promise.resolve(new Response(JSON.stringify([{
        id: 'd1', name: '客服集', created_at: '2026-01-01', version_count: 1, latest_version: 1, latest_case_count: 1,
      }])))
      if (url.endsWith('/versions')) return Promise.resolve(new Response(JSON.stringify([{
        id: 'v1', dataset_id: 'd1', version: 1, case_count: 1, source_filename: 'data.jsonl', created_at: '2026-01-01',
      }])))
      return Promise.resolve(new Response(JSON.stringify({
        id: 'v1', dataset_id: 'd1', version: 1, case_count: 1, source_filename: 'data.jsonl', created_at: '2026-01-01',
        total: 1, offset: 0, limit: 50, cases: [{ case_id: 'q1', question: '如何退款？', reference_answer: null,
          reference_chunks: [{ text: '优先联系支持', document_id: 'doc-a' }, { text: '退款需审核', document_id: 'doc-b' }],
        }],
      })))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<DatasetPage />)

    const detail = await screen.findByRole('region', { name: '如何退款？' })
    const chunks = within(detail).getAllByRole('listitem')
    expect(chunks).toHaveLength(2)
    expect(chunks[0].textContent).toContain('doc-a')
    expect(chunks[1].textContent).toContain('doc-b')
  })

  it('shows line and field errors without closing the import dialog', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/datasets') return Promise.resolve(new Response('[]'))
      return Promise.resolve(new Response(JSON.stringify({
        error: 'validation_failed', issues: [{ line: 2, field: 'question', code: 'missing_field', message: '问题不能为空' }],
      }), { status: 422 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DatasetPage />)
    await screen.findByText('暂无数据集')
    await user.click(screen.getByRole('button', { name: '导入样本' }))
    const dialog = screen.getByRole('dialog', { name: '导入样本' })
    await user.type(within(dialog).getByRole('textbox', { name: '数据集名称' }), '测试集')
    const fileInput = within(dialog).getByLabelText('文件') as HTMLInputElement
    await user.upload(fileInput, new File(['invalid'], 'cases.csv', { type: 'text/csv' }))
    expect(fileInput.files).toHaveLength(1)
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('第 2 行 · question：问题不能为空'))
    expect(screen.getByRole('dialog', { name: '导入样本' })).toBeTruthy()
  })
})
