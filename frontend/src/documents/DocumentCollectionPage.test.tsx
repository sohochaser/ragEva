// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DocumentCollectionPage } from './DocumentCollectionPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('DocumentCollectionPage', () => {
  it('shows the document and file-level error when an upload fails', async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/document-collections') {
        if (options?.method !== 'POST') return Promise.resolve(new Response('[]'))
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
    await screen.findByText(/暂无文档集合/)
    await user.click(screen.getByRole('button', { name: /上传原文/ }))
    const dialog = screen.getByRole('dialog', { name: /上传原文/ })
    await user.type(within(dialog).getByRole('textbox', { name: /集合名称/ }), '测试集合')
    await user.upload(within(dialog).getByLabelText(/原文文件/), new File(['bad'], 'broken.txt'))
    expect(within(dialog).getByRole('textbox', { name: 'broken.txt · 3 bytes（字节） · Document ID（文档 ID）' })).toBeTruthy()
    expect((within(dialog).getByRole('spinbutton', { name: 'Chunk Size (characters)（切块大小，字符）' }) as HTMLInputElement).value).toBe('1000')
    expect((within(dialog).getByRole('spinbutton', { name: 'Chunk Overlap (characters)（重叠量，字符）' }) as HTMLInputElement).value).toBe('100')
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const form = fetchMock.mock.calls[1][1]?.body as FormData
    expect(form.get('chunk_size')).toBe('1000')
    expect(form.get('chunk_overlap')).toBe('100')
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('broken.txt · File 1（文件 1） · file: 文件必须使用 UTF-8 编码'))
    expect(screen.getByRole('dialog', { name: /上传原文/ })).toBeTruthy()
  })

  it('accepts PDF uploads and shows a file-level extraction error', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/v1/document-collections') {
        if (fetchMock.mock.calls.length === 1) return Promise.resolve(new Response('[]'))
        return Promise.resolve(new Response(JSON.stringify({
          error: 'validation_failed',
          issues: [{ file_index: 0, filename: 'scan.pdf', field: 'file', code: 'no_extractable_text', message: '文件没有可提取文本' }],
        }), { status: 422 }))
      }
      return Promise.reject(new Error('unexpected URL'))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<DocumentCollectionPage />)
    await screen.findByText(/暂无文档集合/)
    await user.click(screen.getByRole('button', { name: /上传原文/ }))
    const dialog = screen.getByRole('dialog', { name: /上传原文/ })
    await user.type(within(dialog).getByRole('textbox', { name: /集合名称/ }), 'PDF 集合')
    const input = within(dialog).getByLabelText(/原文文件/) as HTMLInputElement
    expect(input.accept).toContain('.docx')
    expect(input.accept).toContain('.pdf')
    await user.upload(input, new File(['PDF'], 'scan.pdf', { type: 'application/pdf' }))
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('scan.pdf · File 1（文件 1） · file: 文件没有可提取文本'))
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
    await screen.findByText(/暂无文档集合/)
    await user.click(screen.getByRole('button', { name: /导入 chunk 清单/ }))
    const dialog = screen.getByRole('dialog', { name: /导入 chunk 清单/ })
    await user.type(within(dialog).getByRole('textbox', { name: /集合名称/ }), '已有切块')
    await user.upload(within(dialog).getByLabelText(/清单文件/), new File(['position,document_id,text\n0,doc-a,第一段'], 'chunks.csv'))
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('Line 3（第 3 行） · position'))
    fail = false
    fireEvent.submit(dialog.querySelector('form')!)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /导入 chunk 清单/ })).toBeNull())
    expect(screen.getByText(/无原文文件/)).toBeTruthy()
    const chunks = within(screen.getByRole('region', { name: /chunk 清单/ })).getAllByRole('listitem')
    expect(chunks.map((item) => item.textContent)).toEqual(['#1doc-a3 characters（字符）第一段', '#2doc-b3 characters（字符）第二段'])
  })

  it('shows exact source bytes and counts Unicode chunk characters', async () => {
    const collection = {
      id: 'c2', name: '来源文档', source_kind: 'source_files', chunk_size: 1000, chunk_overlap: 100,
      document_count: 1, created_at: '2026-10-02',
      documents: [{ document_id: 'doc-1', filename: '来源.txt', checksum: 'abc', byte_count: 1234567,
        has_original_file: true, chunks: [{ position: 0, text: 'A😀中' }] }],
      chunks: [{ position: 0, document_id: 'doc-1', text: 'A😀中' }],
    }
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(
      url === '/api/v1/document-collections' ? [collection] : collection,
    )))))
    render(<DocumentCollectionPage />)
    const detail = await screen.findByRole('region', { name: '来源.txt' })
    expect(detail.textContent).toContain('1234567 bytes（字节）')
    expect(detail.textContent).toContain('3 characters（字符）')
    expect(detail.textContent).toContain('A😀中')
  })
})
