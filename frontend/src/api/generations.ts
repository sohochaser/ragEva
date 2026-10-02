import type { components } from './schema'

export type GenerationRun = components['schemas']['GenerationSummary']
export type GenerationCreate = components['schemas']['GenerationCreate']
export type GeneratedCandidate = components['schemas']['GeneratedCandidate']
export type CandidateReviewRequest = components['schemas']['CandidateReviewRequest']
export type CandidateRevision = components['schemas']['CandidateRevision']
export type CandidateReviewIssue = components['schemas']['CandidateReviewIssue']

export class CandidateReviewError extends Error {
  constructor(public issues: CandidateReviewIssue[]) {
    super('候选审核失败')
  }
}

async function readJson<T>(pending: Promise<Response>): Promise<T> {
  const response = await pending
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export const fetchGenerations = () => readJson<GenerationRun[]>(fetch('/api/v1/generations'))
export const fetchGeneration = (id: string) => readJson<GenerationRun>(fetch(`/api/v1/generations/${encodeURIComponent(id)}`))
export const fetchCandidates = (id: string) => readJson<GeneratedCandidate[]>(fetch(`/api/v1/generations/${encodeURIComponent(id)}/candidates`))
export const fetchCandidate = (id: string) => readJson<GeneratedCandidate>(fetch(`/api/v1/candidates/${encodeURIComponent(id)}`))
export const fetchCandidateRevisions = (id: string) => readJson<CandidateRevision[]>(fetch(`/api/v1/candidates/${encodeURIComponent(id)}/revisions`))
export async function reviewCandidate(id: string, body: CandidateReviewRequest): Promise<GeneratedCandidate> {
  const response = await fetch(`/api/v1/candidates/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (response.status === 422) {
    const payload = await response.json() as { issues?: CandidateReviewIssue[] }
    if (payload.issues) throw new CandidateReviewError(payload.issues)
  }
  return readJson<GeneratedCandidate>(Promise.resolve(response))
}
export const startGeneration = (collectionId: string, body: GenerationCreate) => readJson<GenerationRun>(fetch(
  `/api/v1/document-collections/${encodeURIComponent(collectionId)}/generations`,
  { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
))
