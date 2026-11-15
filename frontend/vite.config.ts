import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Mọi request bắt đầu bằng /api được chuyển tới backend FastAPI (cổng 8000).
    // Nhờ vậy frontend gọi "/api/..." mà không lo khác cổng.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
