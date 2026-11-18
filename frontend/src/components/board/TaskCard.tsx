import { memo } from 'react'
import { useSortable } from '@dnd-kit/sortable'
import { CalendarDays, MessageSquare, Mic } from 'lucide-react'
import type { Priority, Task } from '../../api/types'
import { NO_EDIT_REASON } from '../../lib/permissions'
import { dueState, formatDate, PRIORITY } from '../../lib/utils'
import Avatar from '../Avatar'

// Thẻ kiểu Notion: tiêu đề là chính, thông tin phụ nằm một hàng chữ mờ bên dưới (không dùng nhãn nền màu)
const PRIORITY_DOT: Record<Priority, string> = {
  high: 'bg-rose-500',
  medium: 'bg-amber-500',
  low: 'bg-slate-300',
}
const DUE_TEXT = {
  overdue: 'font-medium text-rose-600',
  today: 'font-medium text-amber-700',
  soon: 'text-amber-700',
  later: 'text-slate-500',
}

/** Phần hiển thị của thẻ (dùng cho cả thẻ thật và bản sao đi theo con trỏ khi đang kéo). */
export const TaskCardView = memo(function TaskCardView({ task, done, dragging = false }: { task: Task; done: boolean; dragging?: boolean }) {
  const due = done ? null : dueState(task.due_date)
  return (
    <div
      className={`select-none rounded-lg border border-slate-200 bg-elevated px-3 py-2.5 text-left ${
        dragging
          ? 'cursor-grabbing opacity-95 shadow-xl'
          : 'shadow-[0_1px_2px_rgb(15_23_42/0.06)] transition-[box-shadow,border-color] duration-150 hover:border-slate-300 hover:shadow-md'
      }`}
    >
      <p className={`text-sm font-medium leading-snug ${done ? 'text-slate-400 line-through' : 'text-slate-800'}`}>{task.title}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1" title={`Mức ưu tiên: ${PRIORITY[task.priority].label}`}>
          <span className={`size-1.5 rounded-full ${PRIORITY_DOT[task.priority]}`} aria-hidden="true" />
          {PRIORITY[task.priority].label}
        </span>
        {task.due_date && (
          <span className={`inline-flex items-center gap-1 ${due ? DUE_TEXT[due] : ''}`}>
            <CalendarDays className="size-3" aria-hidden="true" />
            {formatDate(task.due_date)}
          </span>
        )}
        {task.comment_count > 0 && (
          <span className="inline-flex items-center gap-0.5">
            <MessageSquare className="size-3" aria-hidden="true" />
            {task.comment_count}
          </span>
        )}
        {task.meeting_id && (
          <span title="Tạo từ cuộc họp">
            <Mic className="size-3" aria-label="Tạo từ cuộc họp" />
          </span>
        )}
        <span className="ml-auto">
          {task.assignee ? (
            <Avatar user={task.assignee} size="sm" />
          ) : (
            task.assignee_name && (
              <span
                className="inline-flex max-w-[8rem] items-center truncate rounded-full border border-dashed border-slate-300 px-2 py-0.5 text-slate-600"
                title={`${task.assignee_name} — chưa có tài khoản. Người này vào nhóm và nhận tên thì việc chuyển sang tài khoản của họ.`}
              >
                {task.assignee_name}
              </span>
            )
          )}
        </span>
      </div>
    </div>
  )
})

function TaskCard({
  task,
  done,
  disabled,
  locked = false,
  onOpen,
}: {
  task: Task
  done: boolean
  disabled: boolean
  /** Không có quyền kéo / sửa thẻ này (chỉ xem + bình luận) */
  locked?: boolean
  onOpen: (id: number) => void
}) {
  // useSortable: thẻ vừa kéo được, vừa là "mốc" để thả thẻ khác vào trước / sau nó.
  // Thẻ không được phép kéo (disabled) vẫn là mốc thả → vẫn chèn được thẻ khác vào giữa các thẻ đó.
  const { attributes, listeners, setNodeRef, isDragging } = useSortable({
    id: `t-${task.id}`,
    disabled: { draggable: disabled, droppable: false },
  })
  return (
    <div
      ref={setNodeRef}
      // Kiểu Notion: thẻ gốc Ở NGUYÊN CHỖ và mờ đi, một bản sao đi theo con trỏ (xem DragOverlay ở KanbanBoard)
      className={`${isDragging ? 'opacity-40' : ''} ${disabled ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'}`}
      title={locked ? NO_EDIT_REASON : undefined}
      onClick={() => onOpen(task.id)}
      {...attributes}
      {...listeners}
    >
      <TaskCardView task={task} done={done} />
    </div>
  )
}

// memo: thẻ chỉ vẽ lại khi dữ liệu của CHÍNH nó đổi, không vẽ lại theo từng lần chuột nhích lúc kéo thẻ khác
export default memo(TaskCard)
