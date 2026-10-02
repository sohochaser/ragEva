import type { components } from './schema'

export type Target = components['schemas']['TargetSummary']
export type TargetCreate = components['schemas']['TargetCreate']
export type TargetJob = components['schemas']['TargetJobSummary']
export type TargetJobCreate = components['schemas']['TargetJobCreate']
export type TargetJobCase = components['schemas']['TargetJobCase']
export type TargetTest = components['schemas']['TargetTestResponse']

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail ?? `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export async function fetchTargets(): Promise<Target[]> {
  return readJson<Target[]>(await fetch('/api/v1/targets'))
}

export async function addTarget(request: TargetCreate): Promise<Target> {
  return readJson<Target>(await fetch('/api/v1/targets', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }))
}

export async function testTarget(id: string, caseId: string, question: string, evaluationType: 'answer' | 'retrieval' | 'both'): Promise<TargetTest> {
  return readJson<TargetTest>(await fetch(`/api/v1/targets/${encodeURIComponent(id)}/test`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_id: caseId, question, evaluation_type: evaluationType }),
  }))
}

export async function fetchTargetJobs(): Promise<TargetJob[]> {
  return readJson<TargetJob[]>(await fetch('/api/v1/target-jobs'))
}

export async function fetchTargetJob(id: string): Promise<TargetJob> {
  return readJson<TargetJob>(await fetch(`/api/v1/target-jobs/${encodeURIComponent(id)}`))
}

export async function cancelTargetJob(id: string): Promise<TargetJob> {
  return readJson<TargetJob>(await fetch(`/api/v1/target-jobs/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
  }))
}

export async function fetchTargetJobCases(id: string): Promise<TargetJobCase[]> {
  return readJson<TargetJobCase[]>(await fetch(`/api/v1/target-jobs/${encodeURIComponent(id)}/cases`))
}

export async function startTargetJob(request: TargetJobCreate): Promise<TargetJob> {
  return readJson<TargetJob>(await fetch('/api/v1/target-jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }))
}
