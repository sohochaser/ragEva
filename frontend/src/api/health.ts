import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type ServiceState = 'checking' | 'online' | 'offline'

export async function readHealth(path: '/live' | '/ready'): Promise<ServiceState> {
  try {
    const response = await fetch(`/api/v1/health${path}`, { cache: 'no-store' })
    const body = (await response.json()) as HealthResponse
    return response.ok && body.status === 'ok' ? 'online' : 'offline'
  } catch {
    return 'offline'
  }
}
