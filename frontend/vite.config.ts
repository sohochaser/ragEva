import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiUrl = process.env.RAGEVA_API_URL || `http://127.0.0.1:${process.env.RAGEVA_API_PORT || '8000'}`

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': apiUrl,
      '/docs': apiUrl,
      '/openapi.json': apiUrl,
    },
  },
})
