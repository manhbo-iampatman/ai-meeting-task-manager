import { create } from 'zustand'

export type Theme = 'light' | 'dark'

const KEY = 'meetflow-theme'

/** Lần đầu vào: theo thiết lập sáng / tối của máy. Sau đó nhớ lựa chọn của người dùng. */
function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* trình duyệt chặn localStorage (chế độ riêng tư) → dùng thiết lập của máy */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Chế độ tối = class "dark" trên <html>; mọi màu đổi theo nhờ biến CSS (xem index.css). */
function apply(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

type ThemeState = { theme: Theme; toggle: () => void }

export const useTheme = create<ThemeState>((set, get) => {
  const theme = initialTheme()
  apply(theme)
  return {
    theme,
    toggle: () => {
      const next: Theme = get().theme === 'dark' ? 'light' : 'dark'
      apply(next)
      try {
        localStorage.setItem(KEY, next)
      } catch {
        /* không lưu được thì thôi, lần sau lại theo máy */
      }
      set({ theme: next })
    },
  }
})
