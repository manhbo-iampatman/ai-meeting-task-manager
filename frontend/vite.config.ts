import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Hai cách chạy:
//   npm run dev       → http://localhost:5173, chỉ máy này dùng (localhost vẫn được bật cam / mic)
//   npm run dev:lan   → https://<IP-máy>:5173, máy khác trong LAN vào được (phòng Online Meeting).
//                       Cần chứng chỉ tự ký do `scripts/setup_lan.py` tạo trong thư mục certs/.
// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const lan = mode === 'lan'
  const certDir = path.resolve(import.meta.dirname, '../certs')
  const cert = path.join(certDir, 'lan-cert.pem')
  const key = path.join(certDir, 'lan-key.pem')
  if (lan && !(fs.existsSync(cert) && fs.existsSync(key))) {
    throw new Error('Chưa có chứng chỉ HTTPS. Chạy trước: backend\\.venv\\Scripts\\python scripts\\setup_lan.py')
  }

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      // host: true → nghe trên mọi card mạng, không chỉ localhost
      ...(lan ? { host: true, https: { cert: fs.readFileSync(cert), key: fs.readFileSync(key) } } : {}),
      // Trình duyệt chỉ nói chuyện với MỘT địa chỉ (cổng 5173); Vite chuyển tiếp:
      //   /api → backend FastAPI (cổng 8000). ws: true → cả WebSocket (cập nhật realtime).
      //   /rtc → LiveKit (cổng 7880): kênh "tín hiệu" của phòng họp. Hình / tiếng thì đi
      //          thẳng tới LiveKit qua UDP 7882, không qua Vite.
      //   xfwd: true → gắn header X-Forwarded-For = IP thật của người dùng; thiếu nó thì backend
      //   thấy mọi người đều là 127.0.0.1 (giới hạn đăng nhập sai sẽ chặn nhầm cả LAN).
      proxy: {
        '/api': { target: 'http://localhost:8000', ws: true, xfwd: true },
        '/rtc': { target: 'http://localhost:7880', ws: true },
      },
    },
  }
})
