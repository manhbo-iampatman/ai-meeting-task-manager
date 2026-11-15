import axios from 'axios'

// Một "client" dùng chung để gọi backend. Giai đoạn 2 sẽ tự gắn JWT token vào đây.
export const api = axios.create({ baseURL: '/api' })

export type ComponentStatus = {
  status: 'ok' | 'error' | 'not_installed'
  detail?: string
}

export type HealthResponse = {
  app: string
  backend: ComponentStatus
  database: ComponentStatus
  redis: ComponentStatus
  gpu: ComponentStatus
  ai_config: { stt: string; whisper_model: string; llm: string }
}

export const getHealth = () => api.get<HealthResponse>('/health').then((r) => r.data)
