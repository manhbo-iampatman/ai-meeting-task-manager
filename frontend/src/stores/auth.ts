import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../api/types'

// Lưu token + thông tin người dùng. `persist` ghi vào localStorage
// → tải lại trang vẫn còn đăng nhập.
type AuthState = {
  token: string | null
  user: User | null
  setAuth: (token: string, user: User) => void
  setUser: (user: User) => void
  logout: () => void
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: 'meetflow-auth' },
  ),
)
