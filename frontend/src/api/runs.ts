import type { components } from './schema'

export type RunSummary = components['schemas']['RunSummary']
export type RunCreate = components['schemas']['RunCreate']
export type RunCasesPage = components['schemas']['RunCasesPage']

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

export async function fetchRunCases(id: string, offset = 0): Promise<RunCasesPage> {
  return readJson<RunCasesPage>(await fetch(`/api/v1/runs/${encodeURIComponent(id)}/cases?offset=${offset}&limit=100`))
}

export async function createRun(request: RunCreate): Promise<RunSummary> {
  return readJson<RunSummary>(await fetch('/api/v1/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }))
}

export async function cancelRun(id: string): Promise<RunSummary> {
  return readJson<RunSummary>(await fetch(`/api/v1/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }))
}
