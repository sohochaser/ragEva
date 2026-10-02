// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PrimaryNavigation, StatusDashboard } from './App'

afterEach(cleanup)

describe('PrimaryNavigation', () => {
  it('keeps all workspaces available and marks the active page', async () => {
    const onNavigate = vi.fn()
    const user = userEvent.setup()
    render(<PrimaryNavigation page="documents" onNavigate={onNavigate} />)

    const nav = screen.getByRole('navigation', { name: /主导航/ })
    expect(within(nav).getAllByRole('button')).toHaveLength(8)
    expect(within(nav).getByRole('button', { name: /文档集合/ }).getAttribute('aria-current')).toBe('page')
    await user.click(screen.getByRole('button', { name: /打开导航/ }))
    expect(screen.getByRole('button', { name: /关闭导航/ }).getAttribute('aria-expanded')).toBe('true')
    await user.click(within(nav).getByRole('button', { name: /评测运行/ }))
    expect(onNavigate).toHaveBeenCalledWith('runs')
    expect(screen.getByRole('button', { name: /打开导航/ }).getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /打开导航/ }))
    await user.click(screen.getByRole('button', { name: /打开导航/ }))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('button', { name: /打开导航/ }).getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /打开导航/ }))
  })
})

describe('StatusDashboard', () => {
  it('shows distinct API and worker states', () => {
    const html = renderToStaticMarkup(
      <StatusDashboard api="online" worker="offline" refreshedAt="12:00:00" onRefresh={vi.fn()} />,
    )
    expect(html).toContain('管理 API')
    expect(html).toContain('任务 Worker')
    expect(html).toContain('运行中')
    expect(html).toContain('不可用')
    expect(html).toContain('Updated（更新于） 12:00:00')
    expect(html).toContain('aria-label="Refresh Status（刷新状态）"')
  })
})
