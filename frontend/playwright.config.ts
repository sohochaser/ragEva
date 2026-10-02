import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

const repoRoot = fileURLToPath(new URL('..', import.meta.url))
const systemChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  workers: 1,
  reporter: 'list',
  outputDir: '../.local/playwright-results',
  use: {
    baseURL: 'http://127.0.0.1:15173',
    browserName: 'chromium',
    launchOptions: {
      executablePath: process.env.RAGEVA_E2E_CHROME || (existsSync(systemChrome) ? systemChrome : undefined),
    },
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'uv run --frozen python scripts/e2e_services.py',
    cwd: repoRoot,
    url: 'http://127.0.0.1:15173/',
    timeout: 60_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
  },
})
