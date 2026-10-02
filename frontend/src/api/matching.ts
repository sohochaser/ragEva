import type { components } from './schema'

export type PreviewResponse = components['schemas']['PreviewResponse']
export type ChunkInput = components['schemas']['ChunkInput']

export async function previewMatching(args: {
  referenceChunks: ChunkInput[]
  predictedChunks: ChunkInput[]
  modelName: string
  modelPath?: string
  offline: boolean
  threshold: number
}): Promise<PreviewResponse> {
  const response = await fetch('/api/v1/matching/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reference_chunks: args.referenceChunks,
      predicted_chunks: args.predictedChunks,
      model_name: args.modelName,
      model_path: args.modelPath || null,
      offline: args.offline,
      threshold: args.threshold,
    }),
  })
  if (!response.ok) {
    const payload = await response.json() as { detail?: string }
    throw new Error(payload.detail ?? `匹配预览失败（${response.status}）`)
  }
  return response.json() as Promise<PreviewResponse>
}
