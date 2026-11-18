// Các thành phần giao diện nhỏ dùng lại nhiều nơi.
// Mọi màu lấy từ hệ thống thiết kế trong index.css (brand-*, slate-*, glass, btn-primary…)
// nên tự đổi theo chế độ sáng / tối, không cần viết `dark:` ở đây.
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import { CircleAlert, LoaderCircle } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary: 'btn-primary',
  secondary: 'border border-slate-300 bg-field text-slate-700 shadow-sm hover:border-slate-400 hover:text-slate-900',
  danger: 'btn-danger',
  ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
}

const SIZES: Record<Size, string> = {
  sm: 'gap-1 rounded-lg px-2.5 py-1.5 text-xs',
  md: 'gap-1.5 rounded-xl px-3.5 py-2 text-sm',
}

/**
 * Nút bấm. `loading` = đang chờ máy chủ: hiện vòng xoay và khóa nút (tránh bấm hai lần).
 * Biểu tượng (lucide) đặt trong nút tự có cỡ 16px.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className = '',
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center font-medium transition duration-150 ease-out active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 [&_svg]:size-4 [&_svg]:shrink-0 ${SIZES[size]} ${VARIANTS[variant]} ${className}`}
    >
      {loading && <LoaderCircle className="animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

/** Lớp dùng chung cho mọi ô nhập / ô chọn (input, select, textarea) để chúng trông giống nhau. */
export const FIELD =
  'rounded-xl border border-slate-300 bg-field px-3 py-2 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15'

export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`w-full ${FIELD} ${className}`} />
}

/** Nhãn của ô nhập. Truyền `htmlFor` = id của ô để trình đọc màn hình đọc đúng nhãn. */
export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-slate-600">
      {children}
    </label>
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <p role="alert" className="flex animate-fade items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0">{children}</span>
    </p>
  )
}

export function Spinner({ text = 'Đang tải…' }: { text?: string }) {
  return (
    <div role="status" className="flex animate-fade items-center justify-center gap-2.5 px-4 py-12 text-sm text-slate-500">
      <LoaderCircle className="size-5 animate-spin text-brand-500" aria-hidden="true" />
      {text}
    </div>
  )
}

/** Khung xương: giữ chỗ cho nội dung đang tải, đỡ giật bố cục hơn dòng chữ "Đang tải…". */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />
}

/** Thẻ kính mờ — bề mặt chính của giao diện. */
export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`glass rounded-2xl border ${className}`}>{children}</div>
}
