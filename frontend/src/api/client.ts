import axios from 'axios'
import { useAuth } from '../stores/auth'

// Một "client" dùng chung để gọi backend.
export const api = axios.create({ baseURL: '/api' })

// Interceptor: tự gắn JWT vào MỌI request → không phải viết lại ở từng chỗ gọi API.
api.interceptors.request.use((config) => {
  const token = useAuth.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Token hết hạn / không hợp lệ (401) → đăng xuất, quay về trang đăng nhập.
api.interceptors.response.use(
  (res) => res,
  (error) => {
    const url: string = error.config?.url ?? ''
    if (error.response?.status === 401 && !url.startsWith('/auth/')) {
      useAuth.getState().logout()
    }
    return Promise.reject(error)
  },
)

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
