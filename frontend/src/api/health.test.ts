import { afterEach, describe, expect, it, vi } from 'vitest'

import { readHealth } from './health'

afterEach(() => vi.unstubAllGlobals())

describe('readHealth', () => {
  it('treats a ready response as online', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', component: 'worker' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    expect(await readHealth('/ready')).toBe('online')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health/ready', { cache: 'no-store' })
  })

  it('shows offline for a stopped worker or unreachable API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ status: 'unavailable', component: 'worker' }),
    }))
    expect(await readHealth('/ready')).toBe('offline')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')))
    expect(await readHealth('/live')).toBe('offline')
  })
})
