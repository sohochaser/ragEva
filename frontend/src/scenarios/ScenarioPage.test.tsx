// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ScenarioPage } from './ScenarioPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('ScenarioPage', () => {
  it('creates a version and previews the saved criteria', async () => {
    const model = { id: 'm1', name: 'Judge', model_name: 'Judge', base_url: 'https://model.example/v1', has_token: true, timeout_seconds: 60, created_at: '2026-01-01' }
    const scenario = { id: 'sv1', scenario_id: 's1', name: '客服', version: 1, faithfulness: '依据证据', relevance: '回答问题', correctness: '匹配答案', prompt_version: 'answer-eval-v1', created_at: '2026-01-01' }
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url === '/api/v1/online-models' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(model)))
      if (url === '/api/v1/online-models') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/scenarios' && options?.method === 'POST') return Promise.resolve(new Response(JSON.stringify(scenario)))
      if (url === '/api/v1/scenarios') return Promise.resolve(new Response('[]'))
      if (url === '/api/v1/scenarios/template') return Promise.resolve(new Response(JSON.stringify({ version: 'answer-eval-v1', system_prompt: 'Fixed rules', variables: ['question'], output_schema: { score: 'number', reason: 'string' } })))
      if (url === '/api/v1/scenarios/s1/versions') return Promise.resolve(new Response(JSON.stringify([scenario])))
      if (url === '/api/v1/scenarios/s1/preview') return Promise.resolve(new Response(JSON.stringify({ scenario_id: 's1', version: 1, model_name: 'Judge', prompt_version: 'answer-eval-v1', metrics: { faithfulness: { status: 'success', score: 0.8, reason: '有依据' }, relevance: { status: 'success', score: 0.9, reason: '相关' }, correctness: { status: 'success', score: 1, reason: '正确' } } })))
      return Promise.resolve(new Response('{}', { status: 404 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<ScenarioPage />)
    await screen.findByRole('button', { name: '新建场景' })
    const modelForm = screen.getByRole('button', { name: '保存模型' }).closest('form')!
    await user.type(within(modelForm).getByRole('textbox', { name: '模型名称' }), 'Judge')
    await user.type(within(modelForm).getByRole('textbox', { name: 'OpenAI 兼容 API 地址' }), 'https://model.example/v1')
    await user.type(within(modelForm).getByLabelText('Bearer Token'), 'private-key')
    await user.click(within(modelForm).getByRole('button', { name: '保存模型' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/online-models', expect.objectContaining({ method: 'POST' })))
    expect(within(modelForm).getByLabelText('Bearer Token').getAttribute('value')).toBe('')

    const scenarioForm = screen.getByRole('button', { name: '创建场景' }).closest('form')!
    await user.type(within(scenarioForm).getByRole('textbox', { name: '场景名称' }), '客服')
    await user.type(within(scenarioForm).getByRole('textbox', { name: '忠实度评价标准' }), '依据证据')
    await user.type(within(scenarioForm).getByRole('textbox', { name: '相关性评价标准' }), '回答问题')
    await user.type(within(scenarioForm).getByRole('textbox', { name: '正确性评价标准' }), '匹配答案')
    await user.click(within(scenarioForm).getByRole('button', { name: '创建场景' }))
    await screen.findByRole('button', { name: '预览评分' })
    const previewForm = screen.getByRole('button', { name: '预览评分' }).closest('form')!
    await user.type(within(previewForm).getByRole('textbox', { name: '问题' }), 'Q')
    await user.type(within(previewForm).getByRole('textbox', { name: '预测答案' }), 'A')
    await user.type(within(previewForm).getByRole('textbox', { name: '标准答案' }), 'A')
    await user.type(within(previewForm).getByRole('textbox', { name: '上下文（每行一个）' }), 'A')
    await user.click(within(previewForm).getByRole('button', { name: '预览评分' }))
    await screen.findByText('忠实度 0.80')
    const request = fetchMock.mock.calls.find(([url]) => url === '/api/v1/scenarios/s1/preview')
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ model_id: 'm1', version: 1, contexts: ['A'] })
  })
})
