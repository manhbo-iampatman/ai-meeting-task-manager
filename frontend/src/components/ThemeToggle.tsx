import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../stores/theme'

/** Nút chuyển giao diện sáng ↔ tối. Lựa chọn được nhớ cho lần sau. */
export default function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggle}
      className="relative rounded-xl p-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
      aria-label={dark ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
      title={dark ? 'Giao diện sáng' : 'Giao diện tối'}
    >
      {/* Hai biểu tượng chồng lên nhau, xoay + mờ dần khi đổi */}
      <Sun className={`size-5 transition duration-300 ${dark ? 'rotate-90 scale-0 opacity-0' : 'rotate-0 scale-100 opacity-100'}`} aria-hidden="true" />
      <Moon
        className={`absolute inset-0 m-auto size-5 transition duration-300 ${dark ? 'rotate-0 scale-100 opacity-100' : '-rotate-90 scale-0 opacity-0'}`}
        aria-hidden="true"
      />
    </button>
  )
}
