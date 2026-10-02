// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { CandidateRevision, DuplicateCheck, GeneratedCandidate } from '../api/generations'
import { CandidateReview } from './CandidateReview'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('edits source order, keeps revisions, and requires an answer before approval', async () => {
  const chunks = [
    { position: 0, document_id: 'doc-a', text: 'first fact' },
    { position: 1, document_id: 'doc-a', text: 'second fact' },
    { position: 2, document_id: 'doc-b', text: 'third fact' },
  ]
  const initial = {
    id: 'candidate-1', run_id: 'run-1', collection_id: 'collection-1', slot_index: 0,
    question: 'Original question', reference_answer: 'Original answer',
    reference_chunks: [chunks[0], chunks[2]], support_positions: [0, 2],
    multi_chunk: true, status: 'pending_review', revision: 0,
    prompt_version: 'candidate-generation-v1', model_name: 'generator-v1', created_at: '2026-10-02T10:00:00Z',
  } satisfies GeneratedCandidate
  let current = initial as GeneratedCandidate
  const revisions: CandidateRevision[] = [{
    revision: 0, question: initial.question, reference_answer: initial.reference_answer,
    reference_chunks: initial.reference_chunks, support_positions: initial.support_positions,
    status: 'pending_review', created_at: initial.created_at,
  }]
  const requests: Array<Record<string, unknown>> = []
  let duplicate: DuplicateCheck | null = {
    id: 1, candidate_id: initial.id, revision: 0, verdict: 'unique', matches: [],
    rule_version: 'candidate-duplicate-v1', checked_at: initial.created_at,
    decision: null, reason: null, decided_at: null,
  }
  const fetchMock = vi.fn((url: string, options?: RequestInit) => {
    if (url === '/api/v1/candidates/candidate-1/duplicate-check') {
      if (options?.method === 'POST') {
        duplicate = {
          ...duplicate!, id: duplicate!.id + 1, verdict: 'suspected',
          matches: [{
            source_kind: 'candidate', source_id: 'earlier', question: 'Earlier question',
            reference_answer: 'Earlier answer', verdict: 'suspected',
            reason: 'shared_answer_or_source', shared_source_count: 1,
            question_similarity: 0.4, term_similarity: 0.2,
          }],
        }
      }
      return Promise.resolve(new Response(JSON.stringify(duplicate)))
    }
    if (url === '/api/v1/candidates/candidate-1/duplicate-history') {
      return Promise.resolve(new Response(JSON.stringify(duplicate ? [duplicate] : [])))
    }
    if (url === '/api/v1/candidates/candidate-1/duplicate-decision' && options?.method === 'POST') {
      const body = JSON.parse(options.body as string) as { reason: string }
      duplicate = { ...duplicate!, decision: 'allow', reason: body.reason, decided_at: '2026-10-02T10:02:00Z' }
      return Promise.resolve(new Response(JSON.stringify(duplicate)))
    }
    if (url === '/api/v1/document-collections/collection-1') {
      return Promise.resolve(new Response(JSON.stringify({ id: 'collection-1', name: 'source', chunks })))
    }
    if (url === '/api/v1/candidates/candidate-1/revisions') {
      return Promise.resolve(new Response(JSON.stringify(revisions)))
    }
    if (url === '/api/v1/candidates/candidate-1' && options?.method === 'PATCH') {
      const body = JSON.parse(options.body as string) as Record<string, unknown>
      requests.push(body)
      if (body.action === 'approve' && !String(body.reference_answer).trim()) {
        return Promise.resolve(new Response(JSON.stringify({
          error: 'validation_failed', issues: [{ field: 'reference_answer', message: '批准前须填写标准答案' }],
        }), { status: 422 }))
      }
      current = {
        ...current, revision: current.revision + 1, question: String(body.question),
        reference_answer: String(body.reference_answer), support_positions: body.support_positions as number[],
        reference_chunks: (body.support_positions as number[]).map((position) => chunks[position]),
        status: body.action === 'approve' ? 'approved' : 'pending_review',
      }
      duplicate = { ...duplicate!, id: duplicate!.id + 1, revision: current.revision }
      revisions.push({
        revision: current.revision, question: current.question, reference_answer: current.reference_answer,
        reference_chunks: current.reference_chunks, support_positions: current.support_positions,
        status: current.status, created_at: '2026-10-02T10:01:00Z',
      })
      return Promise.resolve(new Response(JSON.stringify(current)))
    }
    return Promise.reject(new Error(`Unexpected URL ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)

  function Harness() {
    const [candidate, setCandidate] = useState<GeneratedCandidate>(initial)
    return <CandidateReview candidate={candidate} onUpdated={setCandidate} />
  }
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('button', { name: '审核' }))
  await screen.findByRole('combobox', { name: '添加参考 chunk' })
  await user.selectOptions(screen.getByRole('combobox', { name: '添加参考 chunk' }), '1')
  await user.click(screen.getByRole('button', { name: '添加' }))
  await user.click(screen.getByRole('button', { name: '第 3 个 chunk 上移' }))
  await user.click(screen.getByRole('button', { name: '移除第 1 个 chunk' }))
  await user.clear(screen.getByRole('textbox', { name: '问题' }))
  await user.type(screen.getByRole('textbox', { name: '问题' }), 'Revised question')
  await user.clear(screen.getByRole('textbox', { name: '标准答案' }))
  await user.click(screen.getByRole('button', { name: '保存修订' }))
  await waitFor(() => expect(requests[0]).toMatchObject({
    expected_revision: 0, collection_id: 'collection-1', support_positions: [1, 2],
    question: 'Revised question', reference_answer: '', action: 'save',
  }))

  await user.click(screen.getByRole('button', { name: '批准' }))
  expect((await screen.findByRole('alert')).textContent).toContain('批准前须填写标准答案')
  await user.type(screen.getByRole('textbox', { name: '标准答案' }), 'Revised answer')
  await user.click(screen.getByRole('button', { name: '批准' }))
  await waitFor(() => expect(requests.at(-1)).toMatchObject({ expected_revision: 1, action: 'approve' }))
  expect(await screen.findByText('已批准')).toBeTruthy()
  await user.click(screen.getByText('修订记录 · 3'))
  expect(screen.getByText(/#0 · 待审核/)).toBeTruthy()
  expect(screen.getByText(/#2 · 已批准/)).toBeTruthy()
  expect(screen.getByText('Original answer')).toBeTruthy()
  expect(screen.getByText('未发现重复')).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '重新查重' }))
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/candidates/candidate-1/duplicate-check', { method: 'POST' })
  expect(await screen.findByText('疑似重复 · 待确认')).toBeTruthy()
  await user.type(screen.getByRole('textbox', { name: '非重复放行理由' }), 'Different fact')
  await user.click(screen.getByRole('button', { name: '确认放行' }))
  expect(await screen.findByText('放行理由：Different fact')).toBeTruthy()
})
