import { isAxiosError } from 'axios'
import type { Priority } from '../api/types'

/** Lấy thông báo lỗi dễ đọc từ response của backend. */
export function errorMessage(err: unknown, fallback = 'Đã có lỗi xảy ra'): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    // Lỗi 422 (sai định dạng) trả về mảng
    if (Array.isArray(detail) && detail[0]?.msg) {
      const msg = String(detail[0].msg).replace(/^Value error, /, '')
      if (msg.includes('valid email')) return 'Email không hợp lệ'
      if (msg.includes('at least')) return 'Giá trị quá ngắn'
      return msg
    }
    if (!err.response) return 'Không kết nối được máy chủ'
  }
  return fallback
}

export const PRIORITY: Record<Priority, { label: string; className: string }> = {
  high: { label: 'Cao', className: 'bg-rose-100 text-rose-700' },
  medium: { label: 'Trung bình', className: 'bg-amber-100 text-amber-700' },
  low: { label: 'Thấp', className: 'bg-slate-100 text-slate-600' },
}

/** Ngày hôm nay dạng YYYY-MM-DD theo giờ máy (không dùng toISOString vì lệch múi giờ). */
export function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export type DueState = 'overdue' | 'today' | 'soon' | 'later'

export function dueState(due: string | null): DueState | null {
  if (!due) return null
  const today = todayISO()
  if (due < today) return 'overdue'
  if (due === today) return 'today'
  const diff = (new Date(due).getTime() - new Date(today).getTime()) / 86400000
  return diff <= 2 ? 'soon' : 'later'
}

export function formatDate(iso: string | null): string {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'vừa xong'
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`
  return `${Math.floor(s / 86400)} ngày trước`
}

/** 75.4 → "1:15", 3725 → "1:02:05" */
export function formatClock(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return '--:--'
  const s = Math.floor(sec)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${r}` : `${m}:${r}`
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return ''
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
