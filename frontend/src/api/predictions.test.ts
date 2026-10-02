import { afterEach, describe, expect, it, vi } from 'vitest'

import { importPredictionBatch } from './predictions'

afterEach(() => vi.unstubAllGlobals())

describe('importPredictionBatch', () => {
  it('sends selected dataset version and field mapping without target HTTP calls', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'batch-1' }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    await importPredictionBatch({
      file: new File(['id,answer\nq1,A1'], 'predictions.csv'),
      datasetId: 'dataset-1', datasetVersion: 2, evaluationType: 'answer',
      mapping: { case_id: 'id', answer: 'answer' },
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/predictions/import')
    const form = init.body as FormData
    expect(form.get('dataset_id')).toBe('dataset-1')
    expect(form.get('dataset_version')).toBe('2')
    expect(form.get('evaluation_type')).toBe('answer')
    expect(JSON.parse(form.get('mapping') as string)).toEqual({ case_id: 'id', answer: 'answer' })
  })
})
