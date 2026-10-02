import { Play, Plus, RefreshCw, Save } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { addModel, addScenario, fetchModels, fetchPromptTemplate, fetchScenarios, fetchScenarioVersions, previewScenario, updateScenario, type OnlineModel, type PromptTemplate, type Scenario, type ScenarioCriteria, type ScenarioPreview } from '../api/scenarios'
import { uiError } from '../ui/text'

const metrics = [
  ['faithfulness', 'Faithfulness（忠实度）'], ['relevance', 'Relevance（相关性）'], ['correctness', 'Correctness（正确性）'],
] as const

const blankCriteria: ScenarioCriteria = { faithfulness: '', relevance: '', correctness: '' }

export function ScenarioPage() {
  const [models, setModels] = useState<OnlineModel[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [versions, setVersions] = useState<Scenario[]>([])
  const [template, setTemplate] = useState<PromptTemplate | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [selectedVersion, setSelectedVersion] = useState(1)
  const [name, setName] = useState('')
  const [criteria, setCriteria] = useState<ScenarioCriteria>(blankCriteria)
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelId, setModelId] = useState('')
  const [token, setToken] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [reference, setReference] = useState('')
  const [contexts, setContexts] = useState('')
  const [preview, setPreview] = useState<ScenarioPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [scenarioItems, modelItems, prompt] = await Promise.all([fetchScenarios(), fetchModels(), fetchPromptTemplate()])
      setScenarios(scenarioItems); setModels(modelItems); setTemplate(prompt)
      setSelectedId((id) => id || scenarioItems[0]?.scenario_id || '')
      setModelId((id) => id || modelItems[0]?.id || '')
      setError('')
    } catch (cause) { setError(uiError(cause, 'Unable to load scenarios', '无法读取场景')) }
  }, [])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!selectedId) { setVersions([]); return }
    let active = true
    void fetchScenarioVersions(selectedId).then((items) => {
      if (!active) return
      setVersions(items)
      setSelectedVersion(items[0]?.version ?? 1)
      if (items[0]) setCriteria({ faithfulness: items[0].faithfulness, relevance: items[0].relevance, correctness: items[0].correctness })
      setPreview(null)
    }).catch((cause: unknown) => { if (active) setError(uiError(cause, 'Unable to load versions', '无法读取版本')) })
    return () => { active = false }
  }, [selectedId])

  function chooseVersion(version: number) {
    const item = versions.find((entry) => entry.version === version)
    setSelectedVersion(version)
    if (item) setCriteria({ faithfulness: item.faithfulness, relevance: item.relevance, correctness: item.correctness })
    setPreview(null)
  }

  async function saveScenario(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const saved = selectedId
        ? await updateScenario(selectedId, criteria)
        : await addScenario({ name: name.trim(), ...criteria })
      setScenarios((items) => [saved, ...items.filter((item) => item.scenario_id !== saved.scenario_id)])
      setSelectedId(saved.scenario_id)
      setSelectedVersion(saved.version)
      setVersions((items) => [saved, ...items])
      setName(''); setPreview(null)
    } catch (cause) { setError(uiError(cause, 'Unable to save scenario', '保存场景失败')) }
    finally { setBusy(false) }
  }

  async function saveModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const saved = await addModel({ name: modelName.trim(), base_url: baseUrl.trim(), model_name: modelName.trim(), bearer_token: token || null, timeout_seconds: 60 })
      setModels((items) => [saved, ...items]); setModelId(saved.id)
      setModelName(''); setBaseUrl(''); setToken('')
    } catch (cause) { setError(uiError(cause, 'Unable to save model', '保存模型失败')) }
    finally { setBusy(false) }
  }

  async function runPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setPreview(null)
    try {
      setPreview(await previewScenario(selectedId, {
        model_id: modelId, version: selectedVersion, question: question.trim(), answer: answer.trim(),
        reference_answer: reference.trim(), contexts: contexts.split('\n').map((line) => line.trim()).filter(Boolean),
      }))
    } catch (cause) { setError(uiError(cause, 'Preview failed', '预览失败')) }
    finally { setBusy(false) }
  }

  return <>
    <header className="page-header"><div><p className="eyebrow">Workspace（工作台）</p><h1>Evaluation Scenarios（评价场景）</h1></div><button type="button" className="refresh-button" title="Refresh Scenarios（刷新场景）" aria-label="Refresh Scenarios（刷新场景）" onClick={() => void reload()}><RefreshCw size={17} /></button></header>
    {error && <p className="page-error" role="alert">{error}</p>}
    <section className="scenario-models"><div className="section-heading"><h2>Online Judge Models（在线评分模型）</h2><span>{models.length} configurations（{models.length} 个配置）</span></div><form className="scenario-model-form" onSubmit={(event) => void saveModel(event)}><label className="form-group"><span className="form-label">Model Name（模型名称）</span><input value={modelName} required onChange={(event) => setModelName(event.target.value)} /></label><label className="form-group"><span className="form-label">OpenAI-Compatible API URL（OpenAI 兼容 API 地址）</span><input type="url" value={baseUrl} placeholder="https://.../v1" required onChange={(event) => setBaseUrl(event.target.value)} /></label><label className="form-group"><span className="form-label">Bearer Token（令牌）</span><input type="password" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} /></label><button type="submit" className="secondary-button" disabled={busy}><Plus size={15} />Save Model（保存模型）</button></form></section>
    <div className="scenario-layout"><aside className="scenario-list"><div className="pane-heading"><h2>Scenarios（场景）</h2><span>{scenarios.length}</span></div><button type="button" className={`dataset-row ${selectedId ? '' : 'active'}`} onClick={() => { setSelectedId(''); setCriteria(blankCriteria); setVersions([]); setPreview(null) }}><strong>New Scenario（新建场景）</strong></button>{scenarios.map((item) => <button type="button" className={`dataset-row ${selectedId === item.scenario_id ? 'active' : ''}`} key={item.scenario_id} onClick={() => setSelectedId(item.scenario_id)}><strong>{item.name}</strong><span>v{item.version}</span></button>)}</aside><div className="scenario-main"><div className="dataset-toolbar"><div><h2>{selectedId ? scenarios.find((item) => item.scenario_id === selectedId)?.name : 'New Scenario（新建场景）'}</h2><span>{selectedId ? `Prompt Version（提示词版本） ${versions[0]?.prompt_version ?? ''}` : 'Enter Three Evaluation Criteria（填写三项评价标准）'}</span></div>{selectedId && <label className="version-picker">Version（版本） <select aria-label="Scenario Version（场景版本）" value={selectedVersion} onChange={(event) => chooseVersion(Number(event.target.value))}>{versions.map((item) => <option key={item.id} value={item.version}>v{item.version}</option>)}</select></label>}</div>
      <form className="scenario-form" onSubmit={(event) => void saveScenario(event)}>{!selectedId && <label className="form-group"><span className="form-label">Scenario Name（场景名称）</span><input value={name} required onChange={(event) => setName(event.target.value)} /></label>}{metrics.map(([key, label]) => <label className="form-group" key={key}><span className="form-label">{label} · Evaluation Criteria（评价标准）</span><textarea value={criteria[key]} required maxLength={4000} onChange={(event) => setCriteria((current) => ({ ...current, [key]: event.target.value }))} /></label>)}<button type="submit" className="primary-button" disabled={busy}><Save size={15} />{selectedId ? 'Save as New Version（保存为新版本）' : 'Create Scenario（创建场景）'}</button></form>
      {template && <details className="scenario-template"><summary>Fixed Prompt Template（固定提示词模板） · {template.version}</summary><p>{template.system_prompt}</p><p>Variables（变量）：{template.variables.join('、')}</p><p>Output（输出）：{JSON.stringify(template.output_schema)}</p></details>}
      {selectedId && <section className="scenario-preview"><div className="section-heading"><h2>Single-Case Preview (0–1, unitless)（单题预览，0–1，无单位）</h2></div><form onSubmit={(event) => void runPreview(event)}><label className="form-group"><span className="form-label">Judge Model（评分模型）</span><select value={modelId} required onChange={(event) => setModelId(event.target.value)}>{models.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model_name}</option>)}</select></label><label className="form-group"><span className="form-label">Question（问题）</span><input value={question} required onChange={(event) => setQuestion(event.target.value)} /></label><label className="form-group"><span className="form-label">Predicted Answer（预测答案）</span><textarea value={answer} required onChange={(event) => setAnswer(event.target.value)} /></label><label className="form-group"><span className="form-label">Reference Answer（标准答案）</span><textarea value={reference} required onChange={(event) => setReference(event.target.value)} /></label><label className="form-group"><span className="form-label">Contexts (one per line)（上下文，每行一个）</span><textarea value={contexts} required onChange={(event) => setContexts(event.target.value)} /></label><button type="submit" className="secondary-button" disabled={busy || !modelId}><Play size={15} />Preview Scores（预览评分）</button></form>{preview && <div className="scenario-preview-results" role="status">{metrics.map(([key, label]) => <div key={key}><strong>{label} {preview.metrics[key]?.score?.toFixed(2) ?? 'Unavailable（不可用）'}</strong><span>{preview.metrics[key]?.reason}</span></div>)}</div>}</section>}
    </div></div>
  </>
}
