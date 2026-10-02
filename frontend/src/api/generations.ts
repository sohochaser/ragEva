import type { components } from './schema'

export type GenerationRun = components['schemas']['GenerationSummary']
export type GenerationCreate = components['schemas']['GenerationCreate']
export type GeneratedCandidate = components['schemas']['GeneratedCandidate']

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
export const startGeneration = (collectionId: string, body: GenerationCreate) => readJson<GenerationRun>(fetch(
  `/api/v1/document-collections/${encodeURIComponent(collectionId)}/generations`,
  { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
))
