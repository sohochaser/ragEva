import { AlertCircle, Check, Copy, RefreshCw, Search } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { fetchRequestLog, fetchRequestLogs, type RequestLogDetail, type RequestLogSummary } from '../api/requestLogs'

function time(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function summaryLabel(item: RequestLogSummary): string {
  return `${item.method} ${item.route}`
}

export function RequestLogViewer() {
  const [recent, setRecent] = useState<RequestLogSummary[]>([])
  const [detail, setDetail] = useState<RequestLogDetail | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | 'failed'>('all')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const selection = useRef(0)

  const loadRecent = useCallback(async () => {
    setLoading(true)
    try {
      setRecent(await fetchRequestLogs())
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '请求日志加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDetail = useCallback(async (requestId: string) => {
    const current = ++selection.current
    setDetailLoading(true)
    setCopied(false)
    setError(null)
    try {
      const result = await fetchRequestLog(requestId)
      if (selection.current === current) setDetail(result)
    } catch (cause) {
      if (selection.current === current) {
        setDetail(null)
        setError(cause instanceof Error ? cause.message : '请求日志加载失败')
      }
    } finally {
      if (selection.current === current) setDetailLoading(false)
    }
  }, [])

  useEffect(() => { void loadRecent() }, [loadRecent])

  const search = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const requestId = query.trim().toLowerCase()
    if (!/^[0-9a-f]{32}$/.test(requestId)) {
      setError('请输入 32 位请求 ID')
      return
    }
    void loadDetail(requestId)
  }

  const refresh = () => {
    void loadRecent()
    if (detail) void loadDetail(detail.request_id)
  }

  const shown = filter === 'failed' ? recent.filter((item) => item.status === 'failed') : recent

  return (
    <section className="request-logs-section" aria-labelledby="request-logs-title">
      <div className="section-heading">
        <h2 id="request-logs-title">Request Logs（请求日志）</h2>
        <button className="refresh-button" type="button" onClick={refresh} title="Refresh Logs（刷新日志）" aria-label="Refresh Logs（刷新日志）"><RefreshCw size={16} aria-hidden="true" /></button>
      </div>
      <form className="request-log-search" onSubmit={search}>
        <label htmlFor="request-log-id">Request ID（请求 ID）</label>
        <div><input id="request-log-id" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="32-character request ID" /><button className="secondary-button" type="submit"><Search size={15} aria-hidden="true" />Find（查找）</button></div>
      </form>
      {error && <p className="request-log-error" role="alert">{error}</p>}
      <div className="request-log-layout">
        <div className="request-log-list">
          <div className="request-log-list-heading">
            <strong>Recent Requests（近期请求）</strong>
            <div className="request-log-filter" role="group" aria-label="Request status（请求状态）">
              <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All（全部）</button>
              <button type="button" aria-pressed={filter === 'failed'} onClick={() => setFilter('failed')}>Errors（错误）</button>
            </div>
          </div>
          {loading && recent.length === 0 ? <p className="request-log-placeholder">Loading（加载中）</p> : shown.length === 0 ? <p className="request-log-placeholder">No Requests（暂无请求）</p> : shown.map((item) => (
            <button key={item.request_id} type="button" className={`request-log-row ${detail?.request_id === item.request_id ? 'active' : ''}`} onClick={() => void loadDetail(item.request_id)}>
              <span className="request-log-row-top"><strong>{summaryLabel(item)}</strong><span className={item.status === 'failed' ? 'request-log-failed' : 'request-log-success'}>{item.status === 'failed' ? 'Error（错误）' : 'OK'}</span></span>
              <span>{time(item.started_at)} · HTTP {item.http_status}</span>
              <code>{item.request_id}</code>
            </button>
          ))}
        </div>
        <div className="request-log-detail" aria-live="polite">
          {detailLoading && !detail ? <p className="request-log-placeholder">Loading（加载中）</p> : detail ? <>
            <div className="request-log-detail-heading">
              <div><h3>{summaryLabel(detail)}</h3><span>{time(detail.started_at)} · HTTP {detail.http_status} · {detail.spans.length} steps（步）</span></div>
              <button className="icon-button" type="button" title="Copy Request ID（复制请求 ID）" aria-label="Copy Request ID（复制请求 ID）" onClick={() => { void navigator.clipboard.writeText(detail.request_id).then(() => setCopied(true)).catch(() => setError('复制失败')) }}><Copy size={16} aria-hidden="true" /></button>
            </div>
            <code className="request-log-id">{detail.request_id}</code>
            {copied && <span className="request-log-copied" role="status"><Check size={14} aria-hidden="true" />Copied（已复制）</span>}
            <ol className="request-log-timeline">{detail.spans.map((span) => <li key={span.span_id} className={span.status === 'failed' ? 'failed' : ''}>
              <span className="request-log-timeline-icon">{span.status === 'failed' ? <AlertCircle size={15} aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}</span>
              <div className="request-log-step"><div className="request-log-step-heading"><strong>{span.name}</strong><span>{span.duration_ms} ms</span></div>
                <small>{time(span.started_at)}{span.parent_span_id ? ` · parent ${span.parent_span_id.slice(0, 8)}` : ''}</small>
                {span.error_code && <p className="request-log-step-error"><strong>{span.error_code}</strong> · {span.error_detail}</p>}
                {Object.keys(span.attributes).length > 0 && <dl>{Object.entries(span.attributes).filter(([key]) => !key.startsWith('error.')).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>}
              </div>
            </li>)}</ol>
          </> : <p className="request-log-placeholder">Select a request（选择请求）</p>}
        </div>
      </div>
    </section>
  )
}
