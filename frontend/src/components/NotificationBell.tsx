import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { listNotifications, markAllRead, markNotificationRead, undoClaim } from '../api/endpoints'
import type { Notification } from '../api/types'
import { errorMessage, formatDate, timeAgo } from '../lib/utils'

function count(p: Notification['payload']): string {
  const parts = []
  if (p.task_count) parts.push(`${p.task_count} việc trên bảng`)
  if (p.draft_count) parts.push(`${p.draft_count} đầu việc nháp`)
  return parts.join(' và ') || 'các việc'
}

function text(n: Notification): string {
  const p = n.payload
  if (n.type === 'task_assigned') return `${p.actor_name ?? 'Ai đó'} giao cho bạn: “${p.task_title}”`
  if (n.type === 'task_overdue') return `Quá hạn (${formatDate(p.due_date ?? null)}): “${p.task_title}”`
  if (n.type === 'name_claimed') return `Bạn đã nhận tên “${p.name}”: ${count(p)} giờ là của bạn`
  if (n.type === 'name_claimed_member') return `${p.claimer_name} đã nhận tên “${p.name}” (${count(p)})`
  if (n.type === 'name_claim_undone') return `${p.actor_name} đã hoàn tác việc bạn nhận tên “${p.name}”`
  return `Sắp đến hạn (${formatDate(p.due_date ?? null)}): “${p.task_title}”`
}

const ICON: Record<Notification['type'], string> = {
  task_assigned: '📌',
  task_due_soon: '⏰',
  task_overdue: '⚠️',
  name_claimed: '🙋',
  name_claimed_member: '🙋',
  name_claim_undone: '↩️',
}

/** Bấm vào thông báo thì đi đâu */
function target(n: Notification): string {
  const p = n.payload
  if (n.type === 'name_claimed') return '/my-tasks'
  if (n.type === 'name_claimed_member' || n.type === 'name_claim_undone') return `/workspaces/${p.workspace_id}`
  return `/boards/${p.board_id}?task=${p.task_id}`
}

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
  // F21: trưởng nhóm hoàn tác một lần nhận tên (nhận nhầm / nhận bậy)
  const undo = useMutation({
    mutationFn: undoClaim,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
      qc.invalidateQueries({ queryKey: ['pending-names'] })
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['workspace'] })
    },
    onError: (e) => alert(errorMessage(e)),
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
              <li key={n.id} className={n.is_read ? '' : 'bg-indigo-50/50'}>
                <button
                  className="flex w-full gap-3 px-4 py-3 text-left hover:bg-slate-50"
                  onClick={() => {
                    if (!n.is_read) readOne.mutate(n.id)
                    setOpen(false)
                    navigate(target(n))
                  }}
                >
                  <span>{ICON[n.type] ?? '🔔'}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-slate-700">{text(n)}</span>
                    <span className="text-xs text-slate-400">
                      {n.payload.board_name ?? n.payload.workspace_name} · {timeAgo(n.created_at)}
                    </span>
                  </span>
                  {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />}
                </button>
                {n.type === 'name_claimed_member' && (
                  <div className="-mt-1 px-4 pb-3 pl-11 text-xs">
                    {n.payload.undone ? (
                      <span className="text-slate-400">Đã hoàn tác</span>
                    ) : (
                      <button
                        className="rounded-md border border-slate-300 bg-white px-2 py-1 font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                        disabled={undo.isPending}
                        title="Nhận nhầm / nhận bậy? Trả các việc về lại tên chữ và gỡ biệt danh vừa thêm"
                        onClick={() => {
                          if (!confirm(`Hoàn tác: các việc mang tên “${n.payload.name}” sẽ trở lại chưa có người nhận?`)) return
                          if (!n.is_read) readOne.mutate(n.id)
                          undo.mutate(n.payload.claim_id!)
                        }}
                      >
                        ↩ Hoàn tác
                      </button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
