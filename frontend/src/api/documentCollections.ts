import type { components } from './schema'

export type CollectionSummary = components['schemas']['CollectionSummary']
export type CollectionDetail = components['schemas']['CollectionDetail']
export type DocumentIssue = components['schemas']['DocumentIssueResponse']
export type ChunkImportIssue = components['schemas']['ChunkImportIssueResponse']

export class CollectionImportError extends Error {
  constructor(public issues: DocumentIssue[]) {
    super('文档导入失败')
  }
}

export class ChunkManifestImportError extends Error {
  constructor(public issues: ChunkImportIssue[]) {
    super('chunk 清单导入失败')
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail ?? `Request failed（请求失败） (${response.status})`)
  }
  return response.json() as Promise<T>
}

export async function fetchCollections(): Promise<CollectionSummary[]> {
  return readJson<CollectionSummary[]>(await fetch('/api/v1/document-collections'))
}

export async function fetchCollection(id: string): Promise<CollectionDetail> {
  return readJson<CollectionDetail>(await fetch(`/api/v1/document-collections/${encodeURIComponent(id)}`))
}

export async function fetchCollectionVersions(id: string): Promise<CollectionSummary[]> {
  return readJson<CollectionSummary[]>(await fetch(`/api/v1/document-collections/${encodeURIComponent(id)}/versions`))
}

export async function createCollection(args: {
  name: string
  files: File[]
  documentIds: (string | null)[]
  chunkSize: number
  chunkOverlap: number
  groupId?: string
  expectedVersion?: number
}): Promise<CollectionDetail> {
  const form = new FormData()
  form.append('name', args.name)
  form.append('chunk_size', String(args.chunkSize))
  form.append('chunk_overlap', String(args.chunkOverlap))
  form.append('document_ids', JSON.stringify(args.documentIds))
  if (args.groupId) form.append('group_id', args.groupId)
  if (args.expectedVersion !== undefined) form.append('expected_version', String(args.expectedVersion))
  args.files.forEach((file) => form.append('files', file))
  const response = await fetch('/api/v1/document-collections', { method: 'POST', body: form })
  if (response.status === 422) {
    const payload = await response.json() as { issues?: DocumentIssue[] }
    if (payload.issues) throw new CollectionImportError(payload.issues)
  }
  return readJson<CollectionDetail>(response)
}

export async function importChunkManifest(
  name: string, file: File, groupId?: string, expectedVersion?: number,
): Promise<CollectionDetail> {
  const form = new FormData()
  form.append('name', name)
  form.append('file', file)
  if (groupId) form.append('group_id', groupId)
  if (expectedVersion !== undefined) form.append('expected_version', String(expectedVersion))
  const response = await fetch('/api/v1/document-collections/import-chunks', { method: 'POST', body: form })
  if (response.status === 422) {
    const payload = await response.json() as { issues?: ChunkImportIssue[] }
    if (payload.issues) throw new ChunkManifestImportError(payload.issues)
  }
  return readJson<CollectionDetail>(response)
}
