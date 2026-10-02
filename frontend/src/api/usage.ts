import type { components } from './schema'

export type UsageSummary = components['schemas']['UsageSummary']

async function fetchUsage(url: string): Promise<UsageSummary> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`用量读取失败（${response.status}）`)
  return response.json() as Promise<UsageSummary>
}

export const fetchRunUsage = (id: string) => fetchUsage(`/api/v1/runs/${encodeURIComponent(id)}/usage`)
export const fetchGenerationUsage = (id: string) => fetchUsage(`/api/v1/generations/${encodeURIComponent(id)}/usage`)
