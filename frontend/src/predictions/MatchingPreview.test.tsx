// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MatchingPreview } from './MatchingPreview'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('MatchingPreview', () => {
  it('previews same-document similarity and exposes cross-document exclusions', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/cases/q1')) return Promise.resolve(new Response(JSON.stringify({
        case_id: 'q1', question: 'Q', reference_answer: null,
        reference_chunks: [{ text: 'gold', document_id: 'doc-a' }],
      })))
      return Promise.resolve(new Response(JSON.stringify({
        model_id: 'fake-v1', threshold: 0.8,
        match_rule_version: 'one-to-one-v1', gain_rule_version: 'ordered-linear-v1',
        scores: [{ k: 10, precision: 0.1, ap: 1, ndcg: 1,
          matches: [{ predicted_index: 0, reference_index: 0, similarity: 0.91 }], decisions: [],
        }],
        pairs: [
          { reference_index: 0, predicted_index: 0, similarity: 0.91, candidate: true, reason: 'candidate' },
          { reference_index: 0, predicted_index: 1, similarity: null, candidate: false, reason: 'document_mismatch' },
        ],
      })))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MatchingPreview datasetId="d1" version={1} prediction={{
      case_id: 'q1', answer: null, latency_ms: null,
      contexts: [
        { text: 'prediction', document_id: 'doc-a', chunk_id: null, source: null },
        { text: 'other', document_id: 'doc-b', chunk_id: null, source: null },
      ],
    }} />)

    await user.click(await screen.findByRole('button', { name: /预览/ }))
    expect(screen.getByRole('spinbutton', { name: 'Similarity Threshold (-1 to 1, unitless)（相似度阈值，-1 至 1，无单位）' })).toBeTruthy()
    expect(within(screen.getAllByRole('table')[0]).getByRole('columnheader', { name: /Precision \(0–1, unitless\)/ })).toBeTruthy()
    const table = (await screen.findAllByRole('table'))[1]
    expect(screen.getByText('0.1000')).toBeTruthy()
    expect(within(table).getByText('0.9100')).toBeTruthy()
    expect(within(table).queryByText(/文档不同/)).toBeNull()
    await user.click(screen.getByRole('button', { name: /全部/ }))
    expect(within(table).getByText(/文档不同/)).toBeTruthy()
    expect(within(table).getByText('Unknown（未知）')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await user.clear(screen.getByRole('combobox', { name: /本地模型/ }))
    await user.type(screen.getByRole('combobox', { name: /本地模型/ }), 'other-model')
    expect((screen.getByRole('spinbutton', { name: /相似度阈值/ }) as HTMLInputElement).value).toBe('')
    expect(screen.getByRole('button', { name: /预览/ }).hasAttribute('disabled')).toBe(true)
  })
})
