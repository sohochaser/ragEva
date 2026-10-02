import { Activity, ArrowUpRight, Database, FileInput, Files, Globe2, Menu, RefreshCw, Server, SlidersHorizontal, Sparkles, Workflow, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { readHealth, type ServiceState } from './api/health'
import { DatasetPage } from './datasets/DatasetPage'
import { DocumentCollectionPage } from './documents/DocumentCollectionPage'
import { GenerationPage } from './generations/GenerationPage'
import { PredictionPage } from './predictions/PredictionPage'
import { RunPage } from './runs/RunPage'
import { ScenarioPage } from './scenarios/ScenarioPage'
import { TargetPage } from './targets/TargetPage'

type StatusDashboardProps = {
  api: ServiceState
  worker: ServiceState
  refreshedAt: string | null
  onRefresh: () => void
}

const labels: Record<ServiceState, string> = {
  checking: '检查中',
  online: '运行中',
  offline: '不可用',
}

type Page = 'documents' | 'generations' | 'datasets' | 'predictions' | 'targets' | 'scenarios' | 'runs' | 'status'

const navigation = [
  { page: 'documents', label: '文档集合', icon: Files },
  { page: 'generations', label: '候选生成', icon: Sparkles },
  { page: 'datasets', label: '数据集', icon: Database },
  { page: 'predictions', label: '预测批次', icon: FileInput },
  { page: 'targets', label: 'HTTP 目标', icon: Globe2 },
  { page: 'scenarios', label: '评价场景', icon: SlidersHorizontal },
  { page: 'runs', label: '评测运行', icon: Workflow },
  { page: 'status', label: '系统状态', icon: Activity },
] as const

export function PrimaryNavigation({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)

  const closeMenu = () => {
    setMenuOpen(false)
    menuButton.current?.focus()
  }

  return (
    <aside className="sidebar" onKeyDown={(event) => { if (event.key === 'Escape' && menuOpen) closeMenu() }}>
      <div className="sidebar-top">
        <div className="brand"><span className="brand-mark">r</span><span>ragEva</span></div>
        <button
          ref={menuButton}
          className="menu-toggle"
          type="button"
          aria-label={menuOpen ? '关闭导航' : '打开导航'}
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
        </button>
      </div>
      <nav id="primary-nav" className={`primary-nav ${menuOpen ? 'nav-open' : ''}`} aria-label="主导航">
        {navigation.map(({ page: target, label, icon: Icon }) => (
          <button
            key={target}
            type="button"
            className={`nav-item ${page === target ? 'nav-active' : ''}`}
            aria-current={page === target ? 'page' : undefined}
            onClick={() => { onNavigate(target); if (menuOpen) closeMenu() }}
          >
            <Icon size={17} aria-hidden="true" />{label}
          </button>
        ))}
      </nav>
      <div className="sidebar-foot">本机工作台</div>
    </aside>
  )
}

function StatusItem({
  title,
  detail,
  state,
  icon,
}: {
  title: string
  detail: string
  state: ServiceState
  icon: React.ReactNode
}) {
  return (
    <div className="status-item">
      <div className="status-icon" aria-hidden="true">{icon}</div>
      <div className="status-copy">
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      <span className={`status-label status-${state}`}>
        <span className="status-dot" aria-hidden="true" />
        {labels[state]}
      </span>
    </div>
  )
}

export function StatusDashboard({ api, worker, refreshedAt, onRefresh }: StatusDashboardProps) {
  return (
    <>
        <header className="page-header">
          <div>
            <p className="eyebrow">WORKSPACE</p>
            <h1>系统状态</h1>
          </div>
          <button className="refresh-button" type="button" onClick={onRefresh} title="刷新状态" aria-label="刷新状态">
            <RefreshCw size={17} aria-hidden="true" />
          </button>
        </header>
        <section className="status-section" aria-labelledby="services-title">
          <div className="section-heading">
            <h2 id="services-title">服务</h2>
            <span>{refreshedAt ? `更新于 ${refreshedAt}` : '正在检查'}</span>
          </div>
          <div className="status-list">
            <StatusItem title="管理 API" detail="本机管理服务" state={api} icon={<Server size={20} />} />
            <StatusItem title="任务 Worker" detail="本地队列处理进程" state={worker} icon={<Workflow size={20} />} />
          </div>
          <a className="api-link" href="/docs" target="_blank" rel="noreferrer">
            API 文档 <ArrowUpRight size={16} aria-hidden="true" />
          </a>
        </section>
    </>
  )
}

export function App() {
  const [page, setPage] = useState<Page>('documents')
  const [datasetFocus, setDatasetFocus] = useState<{ datasetId: string; version: number } | null>(null)
  const [api, setApi] = useState<ServiceState>('checking')
  const [worker, setWorker] = useState<ServiceState>('checking')
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const [apiState, workerState] = await Promise.all([readHealth('/live'), readHealth('/ready')])
    setApi(apiState)
    setWorker(workerState)
    setRefreshedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
  }, [])

  useEffect(() => {
    void refresh()
    const interval = window.setInterval(() => void refresh(), 5000)
    return () => window.clearInterval(interval)
  }, [refresh])

  const navigate = (target: Page) => {
    if (target === 'datasets') setDatasetFocus(null)
    setPage(target)
  }

  return (
    <div className="app-shell">
      <PrimaryNavigation page={page} onNavigate={navigate} />
      <main className="main-content">
        {page === 'documents' && <DocumentCollectionPage />}
        {page === 'generations' && <GenerationPage onOpenCollections={() => setPage('documents')} onOpenDatasets={(version) => { setDatasetFocus({ datasetId: version.dataset_id, version: version.version }); setPage('datasets') }} />}
        {page === 'datasets' && <DatasetPage focusVersion={datasetFocus} />}
        {page === 'predictions' && <PredictionPage />}
        {page === 'targets' && <TargetPage />}
        {page === 'scenarios' && <ScenarioPage />}
        {page === 'runs' && <RunPage />}
        {page === 'status' && <StatusDashboard api={api} worker={worker} refreshedAt={refreshedAt} onRefresh={() => void refresh()} />}
      </main>
    </div>
  )
}
