// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { TraceLink } from './TraceLink'

afterEach(cleanup)

describe('TraceLink', () => {
  const trace = { trace_id: 'a'.repeat(32), span_id: 'b'.repeat(16), expires_at: '2026-11-01T00:00:00Z', status: 'available' as const, url: `http://127.0.0.1:16686/trace/${'a'.repeat(32)}` }

  it('opens a configured Jaeger trace', () => {
    render(<TraceLink trace={trace} />)
    const link = screen.getByRole('link', { name: 'Jaeger trace' })
    expect(link.getAttribute('href')).toBe(trace.url)
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('shows an expired state without a stale link', () => {
    render(<TraceLink trace={{ ...trace, status: 'expired', url: null }} />)
    expect(screen.getByRole('status').textContent).toBe('Trace Expired（Trace 已过期）')
    expect(screen.queryByRole('link')).toBeNull()
  })
})
