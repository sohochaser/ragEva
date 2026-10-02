import type { components } from './schema'

export type RunSummary = components['schemas']['RunSummary']
export type RunCreate = components['schemas']['RunCreate']
export type RunRescore = components['schemas']['RunRescore']
export type RunCasesPage = components['schemas']['RunCasesPage']
export type RunCase = components['schemas']['RunCaseResponse']
export type CaseStatus = RunCase['status']

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail ?? `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export async function fetchRuns(): Promise<RunSummary[]> {
  return readJson<RunSummary[]>(await fetch('/api/v1/runs'))
}

export async function fetchRun(id: string): Promise<RunSummary> {
  return readJson<RunSummary>(await fetch(`/api/v1/runs/${encodeURIComponent(id)}`))
}

export async function fetchRunCases(id: string, offset = 0, status: CaseStatus | '' = ''): Promise<RunCasesPage> {
  const query = new URLSearchParams({ offset: String(offset), limit: '100' })
  if (status) query.set('status', status)
  return readJson<RunCasesPage>(await fetch(`/api/v1/runs/${encodeURIComponent(id)}/cases?${query}`))
}

export function exportRunUrl(id: string, format: 'csv' | 'json', status: CaseStatus | '' = ''): string {
  const query = new URLSearchParams({ format })
  if (status) query.set('status', status)
  return `/api/v1/runs/${encodeURIComponent(id)}/export?${query}`
}

export async function createRun(request: RunCreate): Promise<RunSummary> {
  return readJson<RunSummary>(await fetch('/api/v1/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }))
}

export async function rescoreRun(id: string, request: RunRescore): Promise<RunSummary> {
  return readJson<RunSummary>(await fetch(`/api/v1/runs/${encodeURIComponent(id)}/rescore`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }))
}

export async function cancelRun(id: string): Promise<RunSummary> {
  return readJson<RunSummary>(await fetch(`/api/v1/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }))
}
