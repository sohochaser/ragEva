import { ExternalLink } from 'lucide-react'
import type { components } from '../api/schema'

export type TraceReference = components['schemas']['TraceReference']

export function TraceLink({ trace, label = 'Jaeger trace' }: { trace?: TraceReference | null, label?: string }) {
  if (!trace) return null
  if (trace.status === 'expired') return <span className="trace-status" role="status">Trace Expired（Trace 已过期）</span>
  if (trace.status === 'unconfigured' || !trace.url) return <span className="trace-status">Jaeger Not Configured（Jaeger 未配置）</span>
  return <a className="trace-link" href={trace.url} target="_blank" rel="noopener noreferrer" title={`Trace ${trace.trace_id}`}><ExternalLink size={14} />{label}</a>
}
