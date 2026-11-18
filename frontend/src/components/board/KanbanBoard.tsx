import { useEffect, useRef, useState } from 'react'
import { canEditTask } from '../../lib/permissions'
import { useAuth } from '../../stores/auth'
import {
  closestCorners,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useQueryClient } from '@tanstack/react-query'
import { moveTask } from '../../api/endpoints'
import type { BoardDetail, Task } from '../../api/types'
import { errorMessage } from '../../lib/utils'
import KanbanColumn from './KanbanColumn'
import { TaskCardView } from './TaskCard'

// Khóa dùng cho dnd-kit: cột "c-<id>", thẻ "t-<id>"
type Items = Record<string, Task[]>
const colKey = (id: number) => `c-${id}`
const taskKey = (id: number) => `t-${id}`

function buildItems(board: BoardDetail): Items {
  return Object.fromEntries(board.columns.map((c) => [colKey(c.id), c.tasks]))
}

/**
 * Bảng Kanban kéo-thả.
 *
 * Cách làm "optimistic update" (cập nhật lạc quan): khi thả thẻ, giao diện đổi NGAY
 * (không chờ server) rồi mới gọi API. Nếu API lỗi thì tải lại dữ liệu thật từ server.
 * → người dùng thấy mượt, không bị giật.
 */
export default function KanbanBoard({
  board,
  filterFn,
  onOpenTask,
}: {
  board: BoardDetail
  filterFn: ((t: Task) => boolean) | null
  onOpenTask: (id: number) => void
}) {
  const qc = useQueryClient()
  const me = useAuth((s) => s.user)!
  const canEdit = (t: Task) => canEditTask(t, board.owner_id, me.id)
  const [items, setItems] = useState<Items>(() => buildItems(board))
  const [active, setActive] = useState<Task | null>(null)
  const origin = useRef<{ col: string; index: number } | null>(null)

  // Dữ liệu server thay đổi (vd. người khác vừa kéo thẻ) → cập nhật, trừ khi mình đang kéo
  useEffect(() => {
    if (!active) setItems(buildItems(board))
  }, [board, active])

  const sensors = useSensors(
    // Phải kéo ít nhất 5px mới tính là kéo → bấm nhẹ vẫn mở được chi tiết thẻ
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const findContainer = (id: string, src: Items = items): string | undefined => {
    if (id in src) return id
    return Object.keys(src).find((k) => src[k].some((t) => taskKey(t.id) === id))
  }

  function onDragStart({ active }: DragStartEvent) {
    const id = String(active.id)
    const col = findContainer(id)
    if (!col) return
    const index = items[col].findIndex((t) => taskKey(t.id) === id)
    origin.current = { col, index }
    setActive(items[col][index])
  }

  // Đang kéo qua cột khác → chuyển thẻ sang cột đó ngay để thấy trước vị trí
  function onDragOver({ active, over }: DragOverEvent) {
    if (!over) return
    const activeId = String(active.id)
    const overId = String(over.id)
    setItems((prev) => {
      const from = findContainer(activeId, prev)
      const to = findContainer(overId, prev)
      if (!from || !to || from === to) return prev
      const moving = prev[from].find((t) => taskKey(t.id) === activeId)
      if (!moving) return prev
      const overIndex = prev[to].findIndex((t) => taskKey(t.id) === overId)
      const insertAt = overIndex >= 0 ? overIndex : prev[to].length
      return {
        ...prev,
        [from]: prev[from].filter((t) => taskKey(t.id) !== activeId),
        [to]: [...prev[to].slice(0, insertAt), moving, ...prev[to].slice(insertAt)],
      }
    })
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    const activeId = String(active.id)
    setActive(null)
    if (!over) {
      setItems(buildItems(board))
      return
    }
    const overId = String(over.id)
    const col = findContainer(activeId)
    const overCol = findContainer(overId)
    if (!col || !overCol) return

    // Sắp xếp lại trong cùng cột
    let next = items
    if (col === overCol) {
      const oldIndex = items[col].findIndex((t) => taskKey(t.id) === activeId)
      const newIndex = overId === col ? items[col].length - 1 : items[col].findIndex((t) => taskKey(t.id) === overId)
      if (oldIndex !== newIndex && newIndex >= 0) next = { ...items, [col]: arrayMove(items[col], oldIndex, newIndex) }
    }
    const finalIndex = next[col].findIndex((t) => taskKey(t.id) === activeId)
    setItems(next)
    if (origin.current && origin.current.col === col && origin.current.index === finalIndex) return

    const columnId = Number(col.slice(2))
    const taskId = Number(activeId.slice(2))

    // Cập nhật cache ngay (optimistic) để bảng không "nhảy" về chỗ cũ
    qc.setQueryData<BoardDetail>(['board', board.id], (old) =>
      old && {
        ...old,
        columns: old.columns.map((c) => ({
          ...c,
          tasks: (next[colKey(c.id)] ?? []).map((t) => (t.id === taskId ? { ...t, column_id: columnId } : t)),
        })),
      },
    )
    moveTask(taskId, columnId, finalIndex)
      .catch((e) => alert(errorMessage(e, 'Không di chuyển được thẻ')))
      .finally(() => qc.invalidateQueries({ queryKey: ['board', board.id] }))
  }

  const dragDisabled = filterFn !== null

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setActive(null)
        setItems(buildItems(board))
      }}
    >
      <div className="flex h-full items-start gap-3">
        {board.columns.map((c) => {
          const all = items[colKey(c.id)] ?? []
          return (
            <KanbanColumn
              key={c.id}
              boardId={board.id}
              column={c}
              tasks={filterFn ? all.filter(filterFn) : all}
              totalCount={all.length}
              dragDisabled={dragDisabled}
              canEdit={canEdit}
              onOpenTask={onOpenTask}
            />
          )
        })}
      </div>
      {/* "Bóng" của thẻ đi theo con trỏ chuột khi kéo */}
      <DragOverlay>
        {active && <TaskCardView task={active} done={false} dragging />}
      </DragOverlay>
    </DndContext>
  )
}
