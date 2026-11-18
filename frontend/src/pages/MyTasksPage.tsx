import { useState } from 'react'
import { CalendarDays, PartyPopper } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { myTasks } from '../api/endpoints'
import type { MyTask } from '../api/types'
import { Spinner } from '../components/ui'
import { dueState, formatDate, PRIORITY } from '../lib/utils'

const GROUPS: { key: string; title: string; match: (t: MyTask) => boolean; tone: string }[] = [
  { key: 'overdue', title: 'Quá hạn', match: (t) => !t.is_done && dueState(t.due_date) === 'overdue', tone: 'text-rose-600' },
  { key: 'today', title: 'Hôm nay', match: (t) => !t.is_done && dueState(t.due_date) === 'today', tone: 'text-amber-600' },
  {
    key: 'upcoming',
    title: 'Sắp tới',
    match: (t) => !t.is_done && ['soon', 'later'].includes(dueState(t.due_date) ?? ''),
    tone: 'text-slate-700',
  },
  { key: 'nodue', title: 'Không có hạn', match: (t) => !t.is_done && !t.due_date, tone: 'text-slate-500' },
  { key: 'done', title: 'Đã hoàn thành', match: (t) => t.is_done, tone: 'text-emerald-600' },
]

export default function MyTasksPage() {
  const [showDone, setShowDone] = useState(false)
  const { data, isLoading } = useQuery({ queryKey: ['my-tasks', showDone], queryFn: () => myTasks(showDone) })

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Việc của tôi</h1>
        <label className="ml-auto flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />
          Hiện cả việc đã xong
        </label>
      </div>
      <p className="mt-1 text-sm text-slate-500">Mọi việc được giao cho bạn ở tất cả các nhóm.</p>

      {isLoading && <Spinner />}
      {data?.length === 0 && (
        <p className="mt-8 rounded-2xl border-2 border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
          <PartyPopper className="mx-auto mb-2 size-8 text-brand-500" aria-hidden="true" />
          Bạn không có việc nào đang chờ.
        </p>
      )}

      {data &&
        GROUPS.map((g) => {
          const list = data.filter(g.match)
          if (list.length === 0) return null
          return (
            <section key={g.key} className="mt-6">
              <h2 className={`mb-2 text-sm font-semibold ${g.tone}`}>
                {g.title} ({list.length})
              </h2>
              <ul className="glass divide-y divide-slate-100 overflow-hidden rounded-2xl border">
                {list.map((t) => (
                  <li key={t.id}>
                    <Link to={`/boards/${t.board_id}?task=${t.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 transition-colors hover:bg-slate-50">
                      <span className={`min-w-0 flex-1 text-sm ${t.is_done ? 'text-slate-400 line-through' : ''}`}>{t.title}</span>
                      <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${PRIORITY[t.priority].className}`}>{PRIORITY[t.priority].label}</span>
                      {t.due_date && <span className="text-xs text-slate-500">
                          <CalendarDays className="mr-1 inline size-3.5 align-[-2px]" aria-hidden="true" />
                          {formatDate(t.due_date)}
                        </span>}
                      <span className="w-full text-xs text-slate-400 sm:w-auto">
                        {t.workspace_name} › {t.board_name} › {t.column_name}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
    </div>
  )
}
