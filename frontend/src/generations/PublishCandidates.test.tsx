// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import type { GeneratedCandidate } from '../api/generations'
import { PublishCandidates } from './PublishCandidates'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('publishes approved candidates to a new or existing version', async () => {
  const candidates = [
    { id: 'one', question: 'First question', status: 'approved' },
    { id: 'two', question: 'Second question', status: 'pending_review' },
  ] as GeneratedCandidate[]
  const requests: Array<Record<string, unknown>> = []
  let datasets = [{
    id: 'existing', name: 'Existing gold', created_at: '2026-10-02T00:00:00Z',
    version_count: 1, latest_version: 1, latest_case_count: 1,
  }]
  vi.stubGlobal('fetch', vi.fn((url: string, options?: RequestInit) => {
    if (url === '/api/v1/datasets') {
      return Promise.resolve(new Response(JSON.stringify(datasets)))
    }
    if (url === '/api/v1/candidates/publish' && options?.method === 'POST') {
      const body = JSON.parse(options.body as string) as Record<string, unknown>
      requests.push(body)
      const version = body.dataset_id ? 2 : 1
      if (!body.dataset_id) datasets = [...datasets, {
        ...datasets[0], id: 'new', name: String(body.dataset_name), latest_version: 1,
      }]
      else datasets = datasets.map((item) => item.id === 'existing' ? {
        ...item, latest_version: 2, version_count: 2,
      } : item)
      return Promise.resolve(new Response(JSON.stringify({
        id: `version-${version}`, dataset_id: body.dataset_id || 'new', version,
        case_count: version, source_filename: 'generated-candidates',
        source_collection_ids: ['collection'], created_at: '2026-10-02T00:01:00Z',
      }), { status: 201 }))
    }
    return Promise.reject(new Error(`Unexpected URL ${url}`))
  }))
  const onOpenDatasets = vi.fn()
  const user = userEvent.setup()
  render(<PublishCandidates candidates={candidates} onOpenDatasets={onOpenDatasets} />)
  await screen.findByRole('button', { name: /已有数据集/ })
  expect(screen.queryByText('Second question')).toBeNull()
  await user.click(screen.getByRole('checkbox', { name: 'First question' }))
  await user.type(screen.getByRole('textbox', { name: /数据集名称/ }), 'Generated gold')
  await user.click(screen.getByRole('button', { name: /发布为数据集版本/ }))
  await waitFor(() => expect(requests[0]).toMatchObject({
    candidate_ids: ['one'], dataset_name: 'Generated gold', expected_version: null,
  }))
  expect(await screen.findByText('Published（已发布） v1 · 1 cases（1 条样本）')).toBeTruthy()
  await user.click(screen.getByRole('button', { name: /查看数据集/ }))
  expect(onOpenDatasets).toHaveBeenCalledWith(expect.objectContaining({ dataset_id: 'new', version: 1 }))

  await user.click(screen.getByRole('button', { name: /已有数据集/ }))
  await user.selectOptions(screen.getByRole('combobox', { name: /数据集/ }), 'existing')
  await user.click(screen.getByRole('checkbox', { name: 'First question' }))
  await user.click(screen.getByRole('button', { name: /发布为数据集版本/ }))
  await waitFor(() => expect(requests[1]).toMatchObject({
    candidate_ids: ['one'], dataset_id: 'existing', expected_version: 1,
  }))
})
