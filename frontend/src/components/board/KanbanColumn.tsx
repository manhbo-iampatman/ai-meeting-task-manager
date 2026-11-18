import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createTask, deleteColumn, updateColumn } from '../../api/endpoints'
import type { Column, Task } from '../../api/types'
import { errorMessage } from '../../lib/utils'
import TaskCard from './TaskCard'

function AddTaskForm({ boardId, columnId }: { boardId: number; columnId: number }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const add = useMutation({
    mutationFn: () => createTask(boardId, { column_id: columnId, title: title.trim() }),
    onSuccess: () => {
      setTitle('')
      qc.invalidateQueries({ queryKey: ['board', boardId] })
    },
    onError: (e) => alert(errorMessage(e)),
  })

  if (!open) {
    return (
      <button className="w-full rounded-lg px-2 py-1.5 text-left text-sm text-slate-500 hover:bg-slate-200/60" onClick={() => setOpen(true)}>
        + Thêm thẻ
      </button>
    )
  }
  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (title.trim()) add.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-2">
      <textarea
        autoFocus
        rows={2}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e: KeyboardEvent) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
          if (e.key === 'Escape') setOpen(false)
        }}
        placeholder="Nhập tiêu đề công việc… (Enter để thêm)"
        className="w-full resize-none rounded-lg border border-slate-300 bg-white p-2 text-sm outline-none focus:border-indigo-500"
      />
      <div className="flex gap-2">
        <button type="submit" disabled={add.isPending} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700">
          Thêm
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-200">
          Hủy
        </button>
      </div>
    </form>
  )
}

export default function KanbanColumn({
  boardId,
  column,
  tasks,
  dragDisabled,
  canEdit,
  totalCount,
  onOpenTask,
}: {
  boardId: number
  column: Column
  tasks: Task[]
  dragDisabled: boolean
  /** Người đang xem có được kéo thẻ này không (người làm / người tạo / trưởng nhóm) */
  canEdit: (t: Task) => boolean
  totalCount: number
  onOpenTask: (id: number) => void
}) {
  const qc = useQueryClient()
  // useDroppable: cho phép thả thẻ vào cột (kể cả khi cột đang trống)
  const { setNodeRef, isOver } = useDroppable({ id: `c-${column.id}` })
  const [menu, setMenu] = useState(false)
  const refresh = () => qc.invalidateQueries({ queryKey: ['board', boardId] })
  const update = useMutation({
    mutationFn: (body: { name?: string; is_done?: boolean }) => updateColumn(column.id, body),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: () => deleteColumn(column.id), onSuccess: refresh, onError: (e) => alert(errorMessage(e)) })

  return (
    <div className="flex max-h-full w-72 shrink-0 flex-col rounded-xl bg-slate-100">
      <div className="relative flex items-center gap-2 px-3 pb-2 pt-3">
        <h3 className="text-sm font-semibold text-slate-700">{column.name}</h3>
        {column.is_done && <span title="Cột hoàn thành: không nhắc hạn chót">✅</span>}
        <span className="rounded-full bg-slate-200 px-2 text-xs text-slate-600">
          {dragDisabled && tasks.length !== totalCount ? `${tasks.length}/${totalCount}` : totalCount}
        </span>
        <button className="ml-auto rounded px-1.5 text-slate-500 hover:bg-slate-200" onClick={() => setMenu((m) => !m)} aria-label="Tùy chọn cột">
          ⋯
        </button>
        {menu && (
          <div className="absolute right-2 top-9 z-20 w-48 rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-lg" onMouseLeave={() => setMenu(false)}>
            <button
              className="block w-full px-3 py-1.5 text-left hover:bg-slate-50"
              onClick={() => {
                setMenu(false)
                const name = prompt('Tên cột', column.name)
                if (name?.trim()) update.mutate({ name: name.trim() })
              }}
            >
              Đổi tên
            </button>
            <button
              className="block w-full px-3 py-1.5 text-left hover:bg-slate-50"
              onClick={() => {
                setMenu(false)
                update.mutate({ is_done: !column.is_done })
              }}
            >
              {column.is_done ? 'Bỏ đánh dấu "hoàn thành"' : 'Đánh dấu là cột hoàn thành'}
            </button>
            <button
              className="block w-full px-3 py-1.5 text-left text-rose-600 hover:bg-rose-50"
              onClick={() => {
                setMenu(false)
                if (confirm(`Xóa cột “${column.name}” và ${totalCount} thẻ trong cột?`)) remove.mutate()
              }}
            >
              Xóa cột
            </button>
          </div>
        )}
      </div>

      <div ref={setNodeRef} className={`min-h-16 flex-1 space-y-2 overflow-y-auto px-2 pb-2 ${isOver ? 'rounded-lg bg-indigo-50' : ''}`}>
        <SortableContext items={tasks.map((t) => `t-${t.id}`)} strategy={verticalListSortingStrategy}>
          {tasks.map((t) => (
            <TaskCard
              key={t.id}
              task={t}
              done={column.is_done}
              disabled={dragDisabled || !canEdit(t)}
              locked={!canEdit(t)}
              onOpen={onOpenTask}
            />
          ))}
        </SortableContext>
      </div>
      <div className="px-2 pb-2">
        <AddTaskForm boardId={boardId} columnId={column.id} />
      </div>
    </div>
  )
}
