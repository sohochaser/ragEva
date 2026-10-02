import type { components } from './schema'

export type OnlineModel = components['schemas']['OnlineModelSummary']
export type OnlineModelCreate = components['schemas']['OnlineModelCreate']
export type Scenario = components['schemas']['ScenarioVersion']
export type ScenarioCreate = components['schemas']['ScenarioCreate']
export type ScenarioCriteria = components['schemas']['ScenarioCriteria']
export type PromptTemplate = components['schemas']['PromptTemplate']
export type ScenarioPreview = components['schemas']['ScenarioPreviewResponse']
export type ScenarioPreviewRequest = components['schemas']['ScenarioPreviewRequest']

async function readJson<T>(pending: Response | Promise<Response>): Promise<T> {
  const response = await pending
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

async function send<T>(url: string, method: 'POST' | 'PUT', body: object): Promise<T> {
  return readJson<T>(await fetch(url, {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export const fetchModels = () => readJson<OnlineModel[]>(fetch('/api/v1/online-models'))
export const addModel = (body: OnlineModelCreate) => send<OnlineModel>('/api/v1/online-models', 'POST', body)
export const fetchScenarios = () => readJson<Scenario[]>(fetch('/api/v1/scenarios'))
export const fetchScenarioVersions = (id: string) => readJson<Scenario[]>(fetch(`/api/v1/scenarios/${encodeURIComponent(id)}/versions`))
export const fetchPromptTemplate = () => readJson<PromptTemplate>(fetch('/api/v1/scenarios/template'))
export const addScenario = (body: ScenarioCreate) => send<Scenario>('/api/v1/scenarios', 'POST', body)
export const updateScenario = (id: string, body: ScenarioCriteria) => send<Scenario>(`/api/v1/scenarios/${encodeURIComponent(id)}`, 'PUT', body)
export const previewScenario = (id: string, body: ScenarioPreviewRequest) => send<ScenarioPreview>(`/api/v1/scenarios/${encodeURIComponent(id)}/preview`, 'POST', body)
