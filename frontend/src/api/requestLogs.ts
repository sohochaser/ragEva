import type { components } from './schema'

export type RequestLogSummary = components['schemas']['RequestLogSummary']
export type RequestLogDetail = components['schemas']['RequestLogDetail']

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail ?? `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export async function fetchRequestLogs(): Promise<RequestLogSummary[]> {
  return readJson<RequestLogSummary[]>(await fetch('/api/v1/request-logs?limit=50', { cache: 'no-store' }))
}

export async function fetchRequestLog(requestId: string): Promise<RequestLogDetail> {
  return readJson<RequestLogDetail>(await fetch(`/api/v1/request-logs/${encodeURIComponent(requestId)}`, { cache: 'no-store' }))
}
