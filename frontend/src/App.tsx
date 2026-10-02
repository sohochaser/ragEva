import { Activity, ArrowUpRight, Database, FileInput, RefreshCw, Server, Workflow } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { readHealth, type ServiceState } from './api/health'
import { DatasetPage } from './datasets/DatasetPage'
import { PredictionPage } from './predictions/PredictionPage'
import { RunPage } from './runs/RunPage'

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
  const [page, setPage] = useState<'datasets' | 'predictions' | 'runs' | 'status'>('datasets')
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

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">r</span><span>ragEva</span></div>
        <nav aria-label="主导航">
          <button type="button" className={`nav-item ${page === 'datasets' ? 'nav-active' : ''}`} onClick={() => setPage('datasets')}><Database size={17} aria-hidden="true" />数据集</button>
          <button type="button" className={`nav-item ${page === 'predictions' ? 'nav-active' : ''}`} onClick={() => setPage('predictions')}><FileInput size={17} aria-hidden="true" />预测批次</button>
          <button type="button" className={`nav-item ${page === 'runs' ? 'nav-active' : ''}`} onClick={() => setPage('runs')}><Workflow size={17} aria-hidden="true" />评测运行</button>
          <button type="button" className={`nav-item ${page === 'status' ? 'nav-active' : ''}`} onClick={() => setPage('status')}><Activity size={17} aria-hidden="true" />系统状态</button>
        </nav>
        <div className="sidebar-foot">本机工作台</div>
      </aside>
      <main className="main-content">
        <div hidden={page !== 'datasets'}><DatasetPage /></div>
        <div hidden={page !== 'predictions'}><PredictionPage /></div>
        <div hidden={page !== 'runs'}><RunPage /></div>
        {page === 'status' && <StatusDashboard api={api} worker={worker} refreshedAt={refreshedAt} onRefresh={() => void refresh()} />}
      </main>
    </div>
  )
}
