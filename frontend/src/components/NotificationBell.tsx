import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { listNotifications, markAllRead, markNotificationRead } from '../api/endpoints'
import type { Notification } from '../api/types'
import { formatDate, timeAgo } from '../lib/utils'

function text(n: Notification): string {
  const p = n.payload
  if (n.type === 'task_assigned') return `${p.actor_name ?? 'Ai đó'} giao cho bạn: “${p.task_title}”`
  if (n.type === 'task_overdue') return `Quá hạn (${formatDate(p.due_date ?? null)}): “${p.task_title}”`
  return `Sắp đến hạn (${formatDate(p.due_date ?? null)}): “${p.task_title}”`
}

const ICON: Record<Notification['type'], string> = { task_assigned: '📌', task_due_soon: '⏰', task_overdue: '⚠️' }

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const navigate = useNavigate()

  // Hỏi server mỗi 30 giây
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: listNotifications, refetchInterval: 30000 })
  const readOne = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const readAll = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })

  useEffect(() => {
    const onClick = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const unread = data?.unread_count ?? 0

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100"
        aria-label="Thông báo"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-rose-500 px-1 text-center text-[11px] font-semibold leading-[18px] text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-semibold">Thông báo</span>
            {unread > 0 && (
              <button className="text-xs text-indigo-600 hover:underline" onClick={() => readAll.mutate()}>
                Đánh dấu đã đọc hết
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {data?.items.length === 0 && <li className="px-4 py-6 text-center text-sm text-slate-500">Chưa có thông báo</li>}
            {data?.items.map((n) => (
              <li key={n.id}>
                <button
                  className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-slate-50 ${n.is_read ? '' : 'bg-indigo-50/50'}`}
                  onClick={() => {
                    if (!n.is_read) readOne.mutate(n.id)
                    setOpen(false)
                    navigate(`/boards/${n.payload.board_id}?task=${n.payload.task_id}`)
                  }}
                >
                  <span>{ICON[n.type]}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-slate-700">{text(n)}</span>
                    <span className="text-xs text-slate-400">
                      {n.payload.board_name} · {timeAgo(n.created_at)}
                    </span>
                  </span>
                  {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
