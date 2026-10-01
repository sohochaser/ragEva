import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { StatusDashboard } from './App'

describe('StatusDashboard', () => {
  it('shows distinct API and worker states', () => {
    const html = renderToStaticMarkup(
      <StatusDashboard api="online" worker="offline" refreshedAt="12:00:00" onRefresh={vi.fn()} />,
    )
    expect(html).toContain('管理 API')
    expect(html).toContain('任务 Worker')
    expect(html).toContain('运行中')
    expect(html).toContain('不可用')
    expect(html).toContain('更新于 12:00:00')
    expect(html).toContain('aria-label="刷新状态"')
  })
})
