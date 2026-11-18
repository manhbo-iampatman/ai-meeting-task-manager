import type { User } from '../api/types'

// Mỗi người một cặp màu chuyển cố định theo id → nhìn màu là nhận ra người
const COLORS = [
  'from-sky-500 to-blue-700',
  'from-violet-500 to-purple-700',
  'from-green-600 to-teal-700',
  'from-orange-500 to-orange-700',
  'from-rose-500 to-pink-700',
  'from-teal-600 to-cyan-700',
  'from-blue-500 to-indigo-700',
]

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  const last = parts[parts.length - 1] ?? ''
  return (last[0] ?? '?').toUpperCase()
}

export default function Avatar({ user, size = 'md' }: { user: Pick<User, 'id' | 'full_name'>; size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'size-6 text-[11px]' : 'size-8 text-sm'
  return (
    <span
      title={user.full_name}
      className={`inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br font-semibold text-white shadow-sm ring-2 ring-white/60 dark:ring-white/10 ${cls} ${COLORS[user.id % COLORS.length]}`}
    >
      {initials(user.full_name)}
    </span>
  )
}
