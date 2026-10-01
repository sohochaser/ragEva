import { afterEach, describe, expect, it, vi } from 'vitest'

import { DatasetImportError, importDataset } from './datasets'

afterEach(() => vi.unstubAllGlobals())

describe('importDataset', () => {
  it('sends file, target, and only configured field mappings', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'v1', version: 1 }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    await importDataset({
      file: new File(['case_id,question\nq1,hello'], 'cases.csv', { type: 'text/csv' }),
      datasetName: '问答集',
      mapping: { question: 'query', reference_answer: '' },
    })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/datasets/import')
    expect(init.method).toBe('POST')
    const form = init.body as FormData
    expect(form.get('dataset_name')).toBe('问答集')
    expect((form.get('file') as File).name).toBe('cases.csv')
    expect(JSON.parse(form.get('mapping') as string)).toEqual({ question: 'query' })
  })

  it('keeps backend row errors available to the UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: 'validation_failed',
      issues: [{ line: 3, field: 'reference_chunks', code: 'invalid_chunk', message: '缺少 document_id' }],
    }), { status: 422 })))

    await expect(importDataset({ file: new File(['{}'], 'cases.jsonl'), datasetName: '测试', mapping: {} }))
      .rejects.toMatchObject<Partial<DatasetImportError>>({
        issues: [{ line: 3, field: 'reference_chunks', code: 'invalid_chunk', message: '缺少 document_id' }],
      })
  })
})
