import type { User } from '../api/types'

const COLORS = ['bg-sky-500', 'bg-violet-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500', 'bg-teal-500', 'bg-indigo-500']

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  const last = parts[parts.length - 1] ?? ''
  return (last[0] ?? '?').toUpperCase()
}

export default function Avatar({ user, size = 'md' }: { user: Pick<User, 'id' | 'full_name'>; size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'h-6 w-6 text-[11px]' : 'h-8 w-8 text-sm'
  return (
    <span
      title={user.full_name}
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white ${cls} ${COLORS[user.id % COLORS.length]}`}
    >
      {initials(user.full_name)}
    </span>
  )
}
