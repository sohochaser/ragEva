import type { components } from './schema'

export type CollectionSummary = components['schemas']['CollectionSummary']
export type CollectionDetail = components['schemas']['CollectionDetail']
export type DocumentIssue = components['schemas']['DocumentIssueResponse']

export class CollectionImportError extends Error {
  constructor(public issues: DocumentIssue[]) {
    super('文档导入失败')
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`请求失败（${response.status}）`)
  return response.json() as Promise<T>
}

export async function fetchCollections(): Promise<CollectionSummary[]> {
  return readJson<CollectionSummary[]>(await fetch('/api/v1/document-collections'))
}

export async function fetchCollection(id: string): Promise<CollectionDetail> {
  return readJson<CollectionDetail>(await fetch(`/api/v1/document-collections/${encodeURIComponent(id)}`))
}

export async function createCollection(args: {
  name: string
  files: File[]
  documentIds: (string | null)[]
  chunkSize: number
  chunkOverlap: number
}): Promise<CollectionDetail> {
  const form = new FormData()
  form.append('name', args.name)
  form.append('chunk_size', String(args.chunkSize))
  form.append('chunk_overlap', String(args.chunkOverlap))
  form.append('document_ids', JSON.stringify(args.documentIds))
  args.files.forEach((file) => form.append('files', file))
  const response = await fetch('/api/v1/document-collections', { method: 'POST', body: form })
  if (response.status === 422) {
    const payload = await response.json() as { issues?: DocumentIssue[] }
    if (payload.issues) throw new CollectionImportError(payload.issues)
  }
  return readJson<CollectionDetail>(response)
}
