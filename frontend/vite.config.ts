import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Mọi request bắt đầu bằng /api được chuyển tới backend FastAPI (cổng 8000).
    // ws: true → chuyển tiếp cả kết nối WebSocket (cập nhật bảng realtime).
    proxy: {
      '/api': { target: 'http://localhost:8000', ws: true },
    },
  },
})
