import type { components } from './schema'
import { DatasetImportError, type ImportIssue } from './datasets'

export type PredictionBatchSummary = components['schemas']['PredictionBatchSummary']
export type PredictionBatchDetail = components['schemas']['PredictionBatchDetail']
export type Prediction = components['schemas']['PredictionResponse']
export type EvaluationType = 'answer' | 'retrieval' | 'both'

export const predictionFields = [
  'case_id', 'question', 'reference_answer', 'reference_chunks',
  'answer', 'contexts', 'latency_ms',
] as const
export type PredictionField = (typeof predictionFields)[number]
export type PredictionMapping = Partial<Record<PredictionField, string>>

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`请求失败（${response.status}）`)
  return response.json() as Promise<T>
}

export async function fetchPredictionBatches(): Promise<PredictionBatchSummary[]> {
  return readJson<PredictionBatchSummary[]>(await fetch('/api/v1/predictions'))
}

export async function fetchPredictionBatch(id: string, offset = 0): Promise<PredictionBatchDetail> {
  return readJson<PredictionBatchDetail>(await fetch(`/api/v1/predictions/${encodeURIComponent(id)}?offset=${offset}&limit=50`))
}

export async function importPredictionBatch(args: {
  file: File
  evaluationType: EvaluationType
  datasetId?: string
  datasetVersion?: number
  datasetName?: string
  mapping: PredictionMapping
}): Promise<PredictionBatchSummary> {
  const form = new FormData()
  form.append('file', args.file)
  form.append('evaluation_type', args.evaluationType)
  if (args.datasetId) {
    form.append('dataset_id', args.datasetId)
    if (args.datasetVersion) form.append('dataset_version', String(args.datasetVersion))
  } else if (args.datasetName) form.append('dataset_name', args.datasetName)
  const mapping = Object.fromEntries(Object.entries(args.mapping).filter(([, value]) => value?.trim()))
  if (Object.keys(mapping).length) form.append('mapping', JSON.stringify(mapping))
  const response = await fetch('/api/v1/predictions/import', { method: 'POST', body: form })
  if (response.status === 422) {
    const payload = await response.json() as { issues?: ImportIssue[] }
    if (payload.issues) throw new DatasetImportError(payload.issues)
  }
  return readJson<PredictionBatchSummary>(response)
}
