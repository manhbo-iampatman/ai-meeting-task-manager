import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { Task } from '../../api/types'
import { dueState, formatDate, PRIORITY } from '../../lib/utils'
import Avatar from '../Avatar'

const DUE_STYLE = {
  overdue: 'bg-rose-100 text-rose-700',
  today: 'bg-amber-100 text-amber-800',
  soon: 'bg-amber-50 text-amber-700',
  later: 'bg-slate-100 text-slate-600',
}

/** Phần hiển thị của thẻ (dùng cho cả thẻ thật và "bóng" thẻ khi đang kéo). */
export function TaskCardView({ task, done, dragging = false }: { task: Task; done: boolean; dragging?: boolean }) {
  const due = done ? null : dueState(task.due_date)
  return (
    <div
      className={`rounded-lg border border-slate-200 bg-white p-3 text-left shadow-sm ${dragging ? 'rotate-2 shadow-lg ring-2 ring-indigo-300' : 'hover:border-indigo-300'}`}
    >
      <p className={`text-sm ${done ? 'text-slate-400 line-through' : 'text-slate-800'}`}>{task.title}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${PRIORITY[task.priority].className}`}>
          {PRIORITY[task.priority].label}
        </span>
        {task.due_date && (
          <span className={`rounded px-1.5 py-0.5 text-[11px] ${due ? DUE_STYLE[due] : 'bg-slate-100 text-slate-500'}`}>
            📅 {formatDate(task.due_date)}
          </span>
        )}
        {task.comment_count > 0 && <span className="text-[11px] text-slate-500">💬 {task.comment_count}</span>}
        <span className="ml-auto">{task.assignee && <Avatar user={task.assignee} size="sm" />}</span>
      </div>
    </div>
  )
}

export default function TaskCard({
  task,
  done,
  disabled,
  onOpen,
}: {
  task: Task
  done: boolean
  disabled: boolean
  onOpen: (id: number) => void
}) {
  // useSortable: biến thẻ thành phần tử kéo-thả được và sắp xếp được trong cột
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `t-${task.id}`,
    disabled,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`${isDragging ? 'opacity-30' : ''} ${disabled ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'}`}
      onClick={() => onOpen(task.id)}
      {...attributes}
      {...listeners}
    >
      <TaskCardView task={task} done={done} />
    </div>
  )
}
