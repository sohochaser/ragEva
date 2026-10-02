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
})
