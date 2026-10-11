// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import type { UsageSummary } from '../api/usage'
import { UsagePanel } from './UsagePanel'

afterEach(cleanup)

it('labels exact token counts and keeps unavailable counts distinct from zero', () => {
  const usage = {
    call_count: 2,
    totals: {
      input: { actual: { calls: 1, tokens: 12 }, estimated: { calls: 0, tokens: 0 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 1, tokens: 0 } },
      output: { actual: { calls: 1, tokens: 0 }, estimated: { calls: 0, tokens: 0 }, not_applicable: { calls: 0, tokens: 0 }, unknown: { calls: 1, tokens: 0 } },
    },
    calls: [
      { id: 'actual', owner_type: 'run', owner_id: 'run-1', created_at: '2026-10-03', tokenizer: null,
        operation: 'answer_scoring', case_id: 'q1', model_id: 'judge', input_tokens: 12, input_source: 'actual', output_tokens: 0, output_source: 'actual' },
      { id: 'unknown', owner_type: 'run', owner_id: 'run-1', created_at: '2026-10-03', tokenizer: null,
        operation: 'target_rag', case_id: 'q2', model_id: 'target', input_tokens: null, input_source: 'unknown', output_tokens: null, output_source: 'unknown' },
    ],
  } as UsageSummary
  render(<UsagePanel usage={usage} />)
  expect(screen.getByRole('region', { name: 'Model Token Usage（模型 token 用量）' }).textContent).toContain('Actual（实际） 12 tokens（词元）')
  expect(screen.getByText('0 tokens（词元） · Actual（实际）')).toBeTruthy()
  expect(screen.getAllByText('Unknown（未知）').length).toBe(2)
})
