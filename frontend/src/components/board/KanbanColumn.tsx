import { memo, useMemo, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Ellipsis, Plus } from 'lucide-react'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, type SortingStrategy } from '@dnd-kit/sortable'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createTask, deleteColumn, updateColumn } from '../../api/endpoints'
import type { Column, Task } from '../../api/types'
import { errorMessage } from '../../lib/utils'
import TaskCard from './TaskCard'

/**
 * Bảng màu của cột (kiểu Notion): mỗi cột một tông nhạt, tự gán theo thứ tự cột.
 * Cột "hoàn thành" luôn xanh lá. Tên class phải viết đầy đủ để Tailwind nhận ra (không ghép chuỗi).
 * Chế độ tối không cần viết riêng: các biến màu -50 / -100 / -700… đã được định nghĩa lại trong index.css.
 */
type Tone = { column: string; pill: string; dot: string; accent: string; hover: string }
const TONES: Tone[] = [
  { column: 'bg-violet-50', pill: 'bg-violet-100 text-violet-800', dot: 'bg-violet-500', accent: 'text-violet-700', hover: 'hover:bg-violet-100' },
  { column: 'bg-amber-50', pill: 'bg-amber-100 text-amber-800', dot: 'bg-amber-500', accent: 'text-amber-700', hover: 'hover:bg-amber-100' },
  { column: 'bg-sky-50', pill: 'bg-sky-100 text-sky-800', dot: 'bg-sky-500', accent: 'text-sky-700', hover: 'hover:bg-sky-100' },
  { column: 'bg-rose-50', pill: 'bg-rose-100 text-rose-800', dot: 'bg-rose-500', accent: 'text-rose-700', hover: 'hover:bg-rose-100' },
]
const DONE_TONE: Tone = {
  column: 'bg-emerald-50',
  pill: 'bg-emerald-100 text-emerald-800',
  dot: 'bg-emerald-500',
  accent: 'text-emerald-700',
  hover: 'hover:bg-emerald-100',
}

// Kiểu Notion: khi đang kéo, các thẻ khác ĐỨNG YÊN (không dạt ra) → chiến lược sắp xếp "không làm gì"
const stayPut: SortingStrategy = () => null

/** Vạch xanh báo "thẻ sẽ rơi vào đây". Đặt tuyệt đối trong khe giữa hai thẻ nên không làm xô lệch bố cục. */
function DropLine({ className }: { className: string }) {
  return <div aria-hidden="true" className={`pointer-events-none absolute inset-x-0 z-10 h-[3px] rounded-full bg-brand-500 ${className}`} />
}

function AddTaskForm({ boardId, columnId, tone }: { boardId: number; columnId: number; tone: Tone }) {
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
      <button
        className={`flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-sm font-medium transition-colors ${tone.accent} ${tone.hover}`}
        onClick={() => setOpen(true)}
      >
        <Plus className="size-4" aria-hidden="true" />
        Thêm thẻ
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
        className="w-full resize-none rounded-lg border border-slate-300 bg-field p-2 text-sm outline-none focus:border-brand-500"
      />
      <div className="flex gap-2">
        <button type="submit" disabled={add.isPending} className="rounded-lg btn-primary px-3 py-1.5 text-sm  hover:bg-brand-700">
          Thêm
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-200">
          Hủy
        </button>
      </div>
    </form>
  )
}

function KanbanColumn({
  boardId,
  column,
  tasks,
  dragDisabled,
  toneIndex,
  dropIndex,
  canEdit,
  totalCount,
  onOpenTask,
}: {
  boardId: number
  column: Column
  tasks: Task[]
  dragDisabled: boolean
  /** Thứ tự của cột trong các cột chưa hoàn thành → chọn tông màu; -1 = cột hoàn thành (xanh lá) */
  toneIndex: number
  /** Đang kéo một thẻ và nó sẽ rơi vào TRƯỚC thẻ thứ `dropIndex` của cột này (= số thẻ → rơi xuống cuối) */
  dropIndex: number | null
  /** Người đang xem có được kéo thẻ này không (người làm / người tạo / trưởng nhóm) */
  canEdit: (t: Task) => boolean
  totalCount: number
  onOpenTask: (id: number) => void
}) {
  const qc = useQueryClient()
  // useDroppable: cho phép thả thẻ vào cột (kể cả khi cột đang trống).
  // Vùng nhận thả là cả "làn" dọc của cột (cao hết bảng), không chỉ phần có thẻ: thả vào tiêu đề cột
  // hay khoảng trống bên dưới một cột ngắn vẫn tính là thả vào cột đó.
  const { setNodeRef } = useDroppable({ id: `c-${column.id}` })
  const tone = toneIndex < 0 ? DONE_TONE : TONES[toneIndex % TONES.length]
  const [menu, setMenu] = useState(false)
  // Danh sách khóa thẻ PHẢI giữ nguyên "danh tính" khi nội dung không đổi (useMemo).
  // Nếu mỗi lần vẽ lại tạo một mảng mới, thư viện kéo-thả tưởng danh sách vừa đổi → đo lại vị trí →
  // vẽ lại → lại mảng mới → … lặp vô hạn ngay lúc thẻ nhảy sang cột khác (React báo "Maximum update depth").
  const sortableIds = useMemo(() => tasks.map((t) => `t-${t.id}`), [tasks])
  const refresh = () => qc.invalidateQueries({ queryKey: ['board', boardId] })
  const update = useMutation({
    mutationFn: (body: { name?: string; is_done?: boolean }) => updateColumn(column.id, body),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: () => deleteColumn(column.id), onSuccess: refresh, onError: (e) => alert(errorMessage(e)) })

  return (
    <div ref={setNodeRef} className="flex w-72 shrink-0 flex-col self-stretch">
      <div className={`flex max-h-full min-h-0 flex-col rounded-2xl p-1.5 ${tone.column}`} data-column>
        <div className="relative flex items-center gap-2 px-1.5 pb-1.5 pt-1">
          <h3
            className={`inline-flex min-w-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-sm font-medium ${tone.pill}`}
            title={column.is_done ? 'Cột hoàn thành: không nhắc hạn chót' : undefined}
          >
            <span className={`size-2 shrink-0 rounded-full ${tone.dot}`} aria-hidden="true" />
            <span className="truncate">{column.name}</span>
          </h3>
          <span className={`text-sm font-medium ${tone.accent}`}>
            {dragDisabled && tasks.length !== totalCount ? `${tasks.length}/${totalCount}` : totalCount}
          </span>
          <button
            className={`ml-auto rounded-lg p-1 transition-colors ${tone.accent} ${tone.hover}`}
            onClick={() => setMenu((m) => !m)}
            aria-label={`Tùy chọn cột ${column.name}`}
            aria-expanded={menu}
          >
            <Ellipsis className="size-4" aria-hidden="true" />
          </button>
        {menu && (
            <div className="absolute right-2 top-9 z-20 w-52 origin-top-right animate-pop overflow-hidden rounded-xl border border-slate-200 bg-elevated py-1 text-sm shadow-xl" onMouseLeave={() => setMenu(false)}>
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

        <div className="flex min-h-10 flex-1 flex-col gap-2 overflow-y-auto p-1.5">
          <SortableContext items={sortableIds} strategy={stayPut}>
            {tasks.map((t, i) => (
              <div key={t.id} className="relative">
                {dropIndex === i && <DropLine className="-top-[5.5px]" />}
                <TaskCard task={t} done={column.is_done} disabled={dragDisabled || !canEdit(t)} locked={!canEdit(t)} onOpen={onOpenTask} />
                {dropIndex === tasks.length && i === tasks.length - 1 && <DropLine className="-bottom-[5.5px]" />}
              </div>
            ))}
          </SortableContext>
          {tasks.length === 0 && dropIndex !== null && (
            <div className="relative">
              <DropLine className="top-0" />
            </div>
          )}
        </div>
        <div className="px-1.5 pb-1">
          <AddTaskForm boardId={boardId} columnId={column.id} tone={tone} />
        </div>
      </div>
    </div>
  )
}

// memo: lúc kéo thẻ chỉ cột đang có vạch báo chỗ thả vẽ lại, các cột còn lại đứng yên
export default memo(KanbanColumn)
