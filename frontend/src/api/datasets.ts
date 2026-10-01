import type { components } from './schema'

export type DatasetSummary = components['schemas']['DatasetSummary']
export type VersionSummary = components['schemas']['VersionSummary']
export type VersionDetail = components['schemas']['VersionDetail']
export type EvaluationCase = components['schemas']['CaseResponse']
export type ImportIssue = components['schemas']['ImportIssueResponse']

export const fieldNames = ['case_id', 'question', 'reference_answer', 'reference_chunks'] as const
export type FieldName = (typeof fieldNames)[number]
export type FieldMapping = Partial<Record<FieldName, string>>

export class DatasetImportError extends Error {
  constructor(public issues: ImportIssue[]) {
    super('数据集导入失败')
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`请求失败（${response.status}）`)
  return response.json() as Promise<T>
}

export async function fetchDatasets(): Promise<DatasetSummary[]> {
  return readJson<DatasetSummary[]>(await fetch('/api/v1/datasets'))
}

export async function fetchVersions(datasetId: string): Promise<VersionSummary[]> {
  return readJson<VersionSummary[]>(await fetch(`/api/v1/datasets/${encodeURIComponent(datasetId)}/versions`))
}

export async function fetchVersion(datasetId: string, version: number, offset = 0): Promise<VersionDetail> {
  const url = `/api/v1/datasets/${encodeURIComponent(datasetId)}/versions/${version}?offset=${offset}&limit=50`
  return readJson<VersionDetail>(await fetch(url))
}

export async function importDataset(args: {
  file: File
  datasetName?: string
  datasetId?: string
  mapping: FieldMapping
}): Promise<VersionSummary> {
  const form = new FormData()
  form.append('file', args.file)
  if (args.datasetId) form.append('dataset_id', args.datasetId)
  else if (args.datasetName) form.append('dataset_name', args.datasetName)
  const mapping = Object.fromEntries(Object.entries(args.mapping).filter(([, value]) => value?.trim()))
  if (Object.keys(mapping).length) form.append('mapping', JSON.stringify(mapping))
  const response = await fetch('/api/v1/datasets/import', { method: 'POST', body: form })
  if (response.status === 422) {
    const payload = await response.json() as { issues?: ImportIssue[] }
    if (payload.issues) throw new DatasetImportError(payload.issues)
  }
  return readJson<VersionSummary>(response)
}
