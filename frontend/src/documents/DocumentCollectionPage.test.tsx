// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DocumentCollectionPage } from './DocumentCollectionPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('DocumentCollectionPage', () => {
  it('shows the document and file-level error when an upload fails', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/document-collections') {
        if (fetchMock.mock.calls.length === 1) return Promise.resolve(new Response('[]'))
        return Promise.resolve(new Response(JSON.stringify({
          error: 'validation_failed',
          issues: [{ file_index: 0, filename: 'broken.txt', field: 'file', code: 'invalid_encoding', message: '文件必须使用 UTF-8 编码' }],
        }), { status: 422 }))
      }
      return Promise.reject(new Error('unexpected URL'))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DocumentCollectionPage />)
    await screen.findByText('暂无文档集合')
    await user.click(screen.getByRole('button', { name: '上传原文' }))
    const dialog = screen.getByRole('dialog', { name: '上传原文' })
    await user.type(within(dialog).getByRole('textbox', { name: '集合名称' }), '测试集合')
    await user.upload(within(dialog).getByLabelText('原文文件'), new File(['bad'], 'broken.txt'))
    expect(within(dialog).getByRole('textbox', { name: 'broken.txt · 文档 ID' })).toBeTruthy()
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('broken.txt（文件 1） · file：文件必须使用 UTF-8 编码'))
    expect(screen.getByRole('dialog', { name: '上传原文' })).toBeTruthy()
  })

  it('imports a chunk manifest, shows source IDs in order, and reports row errors', async () => {
    const collection = {
      id: 'c1', name: '已有切块', source_kind: 'chunks_only', chunk_size: 0, chunk_overlap: 0,
      created_at: '2026-10-02', document_count: 2,
      documents: [
        { document_id: 'doc-a', filename: null, checksum: null, byte_count: null, has_original_file: false, chunks: [{ position: 0, text: '第一段' }] },
        { document_id: 'doc-b', filename: null, checksum: null, byte_count: null, has_original_file: false, chunks: [{ position: 1, text: '第二段' }] },
      ],
      chunks: [
        { position: 0, document_id: 'doc-a', text: '第一段' },
        { position: 1, document_id: 'doc-b', text: '第二段' },
      ],
    }
    let fail = true
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/document-collections/import-chunks') {
        if (fail) return Promise.resolve(new Response(JSON.stringify({ error: 'validation_failed', issues: [
          { line: 3, field: 'position', code: 'invalid_order', message: 'position 应为 1' },
        ] }), { status: 422 }))
        return Promise.resolve(new Response(JSON.stringify(collection), { status: 201 }))
      }
      if (url === '/api/v1/document-collections') return Promise.resolve(new Response('[]'))
      return Promise.reject(new Error('unexpected URL'))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DocumentCollectionPage />)
    await screen.findByText('暂无文档集合')
    await user.click(screen.getByRole('button', { name: '导入 chunk 清单' }))
    const dialog = screen.getByRole('dialog', { name: '导入 chunk 清单' })
    await user.type(within(dialog).getByRole('textbox', { name: '集合名称' }), '已有切块')
    await user.upload(within(dialog).getByLabelText('清单文件'), new File(['position,document_id,text\n0,doc-a,第一段'], 'chunks.csv'))
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('第 3 行 · position'))
    fail = false
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '导入 chunk 清单' })).toBeNull())
    expect(screen.getByText('无原文文件')).toBeTruthy()
    const chunks = within(screen.getByRole('region', { name: 'chunk 清单' })).getAllByRole('listitem')
    expect(chunks.map((item) => item.textContent)).toEqual(['#1doc-a第一段', '#2doc-b第二段'])
  })
})
