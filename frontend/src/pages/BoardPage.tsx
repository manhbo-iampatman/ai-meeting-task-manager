import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumn, deleteBoard, getBoard, renameBoard } from '../api/endpoints'
import type { Priority, Task } from '../api/types'
import KanbanBoard from '../components/board/KanbanBoard'
import TaskModal from '../components/board/TaskModal'
import { Spinner } from '../components/ui'
import { useBoardSocket } from '../hooks/useBoardSocket'
import { dueState, errorMessage, PRIORITY } from '../lib/utils'
import { useAuth } from '../stores/auth'

type Filters = { q: string; assignee: string; priority: '' | Priority; due: '' | 'overdue' | 'soon' | 'none' }
const EMPTY: Filters = { q: '', assignee: '', priority: '', due: '' }

const selectCls = 'rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm outline-none focus:border-indigo-500'

export default function BoardPage() {
  const id = Number(useParams().id)
  const me = useAuth((s) => s.user)!
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const openTaskId = params.get('task') ? Number(params.get('task')) : null

  const { data: board, isLoading, error } = useQuery({ queryKey: ['board', id], queryFn: () => getBoard(id) })
  const connected = useBoardSocket(id)
  const [filters, setFilters] = useState<Filters>(EMPTY)

  const openTask = useCallback((taskId: number) => setParams({ task: String(taskId) }), [setParams])
  const closeTask = useCallback(() => setParams({}), [setParams])

  const refresh = () => qc.invalidateQueries({ queryKey: ['board', id] })
  const addColumn = useMutation({ mutationFn: (name: string) => createColumn(id, name), onSuccess: refresh })
  const rename = useMutation({ mutationFn: (name: string) => renameBoard(id, name), onSuccess: refresh })
  const remove = useMutation({
    mutationFn: () => deleteBoard(id),
    onSuccess: () => navigate(board ? `/workspaces/${board.workspace_id}` : '/'),
  })

  // Lọc thẻ (F07). null = không lọc → cho phép kéo-thả
  const filterFn = useMemo(() => {
    const active = filters.q || filters.assignee || filters.priority || filters.due
    if (!active) return null
    const q = filters.q.trim().toLowerCase()
    return (t: Task) => {
      if (q && !t.title.toLowerCase().includes(q) && !(t.description ?? '').toLowerCase().includes(q)) return false
      if (filters.assignee === 'me' && t.assignee?.id !== me.id) return false
      if (filters.assignee === 'none' && t.assignee) return false
      if (/^\d+$/.test(filters.assignee) && t.assignee?.id !== Number(filters.assignee)) return false
      if (filters.priority && t.priority !== filters.priority) return false
      const ds = dueState(t.due_date)
      if (filters.due === 'overdue' && ds !== 'overdue') return false
      if (filters.due === 'soon' && ds !== 'today' && ds !== 'soon') return false
      if (filters.due === 'none' && t.due_date) return false
      return true
    }
  }, [filters, me.id])

  if (isLoading) return <Spinner />
  if (error || !board) return <p className="p-8 text-center text-rose-600">{errorMessage(error, 'Không tìm thấy bảng')}</p>

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Thanh tiêu đề + bộ lọc */}
      <div className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Link to={`/workspaces/${board.workspace_id}`} className="text-sm text-slate-500 hover:underline">
            {board.workspace_name}
          </Link>
          <span className="text-slate-300">/</span>
          <h1 className="text-lg font-bold">{board.name}</h1>
          <span
            title={connected ? 'Đang cập nhật theo thời gian thực' : 'Mất kết nối realtime — đang thử lại'}
            className={`flex items-center gap-1 text-xs ${connected ? 'text-emerald-600' : 'text-slate-400'}`}
          >
            <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-slate-300'}`} />
            {connected ? 'Trực tuyến' : 'Ngoại tuyến'}
          </span>
          <div className="ml-auto flex gap-1">
            <button
              className="rounded-lg px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
              onClick={() => {
                const name = prompt('Tên bảng', board.name)
                if (name?.trim()) rename.mutate(name.trim())
              }}
            >
              Đổi tên
            </button>
            <button
              className="rounded-lg px-2 py-1 text-sm text-rose-600 hover:bg-rose-50"
              onClick={() => confirm(`Xóa bảng “${board.name}” và toàn bộ thẻ?`) && remove.mutate()}
            >
              Xóa bảng
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            placeholder="🔍 Tìm công việc…"
            className="w-48 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-500"
          />
          <select className={selectCls} value={filters.assignee} onChange={(e) => setFilters({ ...filters, assignee: e.target.value })}>
            <option value="">Mọi người</option>
            <option value="me">Việc của tôi</option>
            <option value="none">Chưa giao</option>
            {board.members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.full_name}
              </option>
            ))}
          </select>
          <select
            className={selectCls}
            value={filters.priority}
            onChange={(e) => setFilters({ ...filters, priority: e.target.value as Filters['priority'] })}
          >
            <option value="">Mọi mức ưu tiên</option>
            {(Object.keys(PRIORITY) as Priority[]).map((p) => (
              <option key={p} value={p}>
                Ưu tiên {PRIORITY[p].label.toLowerCase()}
              </option>
            ))}
          </select>
          <select className={selectCls} value={filters.due} onChange={(e) => setFilters({ ...filters, due: e.target.value as Filters['due'] })}>
            <option value="">Mọi hạn chót</option>
            <option value="overdue">Quá hạn</option>
            <option value="soon">Sắp đến hạn (≤ 2 ngày)</option>
            <option value="none">Không có hạn</option>
          </select>
          {filterFn && (
            <>
              <button className="text-sm text-indigo-600 hover:underline" onClick={() => setFilters(EMPTY)}>
                Xóa bộ lọc
              </button>
              <span className="text-xs text-slate-500">(Tắt kéo-thả khi đang lọc)</span>
            </>
          )}
        </div>
      </div>

      {/* Vùng bảng: cuộn ngang khi nhiều cột */}
      <div className="min-h-0 flex-1 overflow-x-auto p-4">
        <div className="flex h-full items-start gap-3">
          <KanbanBoard board={board} filterFn={filterFn} onOpenTask={openTask} />
          <button
            className="w-64 shrink-0 rounded-xl border-2 border-dashed border-slate-300 px-3 py-3 text-left text-sm text-slate-500 hover:border-indigo-300 hover:text-indigo-600"
            onClick={() => {
              const name = prompt('Tên cột mới')
              if (name?.trim()) addColumn.mutate(name.trim())
            }}
          >
            + Thêm cột
          </button>
        </div>
      </div>

      {openTaskId && <TaskModal key={openTaskId} taskId={openTaskId} board={board} onClose={closeTask} />}
    </div>
  )
}
