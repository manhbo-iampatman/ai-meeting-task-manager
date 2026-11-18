import { useCallback, useEffect, useRef, useState } from 'react'
import {
  closestCenter,
  closestCorners,
  DndContext,
  DragOverlay,
  getFirstCollision,
  KeyboardSensor,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useSensor,
  useSensors,
  type Active,
  type CollisionDetection,
  type DragStartEvent,
  type Over,
} from '@dnd-kit/core'
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useQueryClient } from '@tanstack/react-query'
import { moveTask } from '../../api/endpoints'
import type { BoardDetail, Task } from '../../api/types'
import { canEditTask } from '../../lib/permissions'
import { errorMessage } from '../../lib/utils'
import { useAuth } from '../../stores/auth'
import KanbanColumn from './KanbanColumn'
import { TaskCardView } from './TaskCard'

// Khóa dùng cho dnd-kit: cột "c-<id>", thẻ "t-<id>"
type Items = Record<string, Task[]>
const colKey = (id: number) => `c-${id}`
const taskKey = (id: number) => `t-${id}`

/** Chỗ thẻ sẽ rơi: vào TRƯỚC thẻ thứ `index` của cột `col` (index = số thẻ của cột → rơi xuống cuối). */
type DropTarget = { col: string; index: number }

function buildItems(board: BoardDetail): Items {
  return Object.fromEntries(board.columns.map((c) => [colKey(c.id), c.tasks]))
}

/**
 * Bảng Kanban kéo-thả kiểu Notion.
 *
 * - Lúc đang kéo, KHÔNG thẻ nào xê dịch: thẻ gốc ở nguyên chỗ và mờ đi, một bản sao đi theo con trỏ,
 *   một VẠCH XANH hiện ở khe giữa hai thẻ để báo "thả ra là rơi vào đây". Dữ liệu chỉ đổi khi thả.
 *   (Cách trước đây cho các thẻ dạt ra và chuyển thẻ sang cột khác ngay lúc đang kéo. Bố cục đổi liên tục
 *   khiến phép dò vị trí "đổi ý" qua lại giữa hai cột → giật, có lúc lặp vô hạn. Bố cục đứng yên thì hết.)
 * - "Optimistic update" (cập nhật lạc quan): khi thả thẻ, giao diện đổi NGAY rồi mới gọi API.
 *   Nếu API lỗi thì tải lại dữ liệu thật từ server.
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
  // useCallback: giữ nguyên hàm qua các lần vẽ lại → memo của KanbanColumn mới có tác dụng
  const canEdit = useCallback((t: Task) => canEditTask(t, board.owner_id, me.id), [board.owner_id, me.id])
  const [items, setItems] = useState<Items>(() => buildItems(board))
  const [active, setActive] = useState<Task | null>(null)
  const [target, setTarget] = useState<DropTarget | null>(null)
  const origin = useRef<DropTarget | null>(null) // thẻ đang kéo xuất phát từ đâu
  const targetRef = useRef<DropTarget | null>(null) // bản mới nhất của `target` cho lúc thả
  const lastOver = useRef<string | null>(null)
  const pointerY = useRef<number | null>(null)

  // Dữ liệu server thay đổi (vd. người khác vừa kéo thẻ) → cập nhật, trừ khi mình đang kéo
  useEffect(() => {
    if (!active) setItems(buildItems(board))
  }, [board, active])

  const sensors = useSensors(
    // Chuột: phải kéo ít nhất 5px mới tính là kéo → bấm nhẹ vẫn mở được chi tiết thẻ
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    // Cảm ứng: nhấn giữ 180ms mới bắt đầu kéo → vuốt để cuộn danh sách vẫn bình thường
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  // Hàm mở thẻ giữ nguyên "danh tính" qua các lần vẽ lại → memo của TaskCard mới có tác dụng
  const openRef = useRef(onOpenTask)
  useEffect(() => {
    openRef.current = onOpenTask
  }, [onOpenTask])
  const openTask = useCallback((id: number) => openRef.current(id), [])

  /**
   * Con trỏ đang chỉ vào thẻ / cột nào? Kết quả CHỈ phụ thuộc vị trí con trỏ. Mỗi cột là một "làn" dọc
   * cao hết bảng, bề ngang cố định.
   *   1. Con trỏ đè lên một thẻ → chính thẻ đó.
   *   2. Con trỏ ở trong làn nhưng không đè thẻ nào (tiêu đề cột, khoảng trống bên dưới) → thẻ có tâm
   *      gần nhất trong cột; cột trống → chính cột đó.
   *   3. Con trỏ ở khe giữa hai cột / ngoài bảng → giữ kết quả lần trước.
   * Bàn phím không có con trỏ → so góc của thẻ đang kéo với các vùng thả.
   */
  const collisionDetection = useCallback<CollisionDetection>(
    (args) => {
      pointerY.current = args.pointerCoordinates?.y ?? null
      let over: string | null = null
      if (args.pointerCoordinates) {
        const hits = pointerWithin(args).map((h) => String(h.id))
        const card = hits.find((id) => id.startsWith('t-'))
        const column = hits.find((id) => id.startsWith('c-'))
        if (card) over = card
        else if (column) {
          const keys = new Set((items[column] ?? []).map((t) => taskKey(t.id)))
          const nearest = closestCenter({
            ...args,
            droppableContainers: args.droppableContainers.filter((c) => keys.has(String(c.id))),
          })
          over = nearest.length > 0 ? String(nearest[0].id) : column
        }
      } else {
        const first = getFirstCollision(closestCorners(args), 'id')
        over = first == null ? null : String(first)
      }
      if (over === null) return lastOver.current ? [{ id: lastOver.current }] : []
      lastOver.current = over
      return [{ id: over }]
    },
    [items],
  )

  const findContainer = (id: string): string | undefined => {
    if (id in items) return id
    return Object.keys(items).find((k) => items[k].some((t) => taskKey(t.id) === id))
  }

  /** Từ thẻ / cột đang bị chỉ vào → chỗ thẻ sẽ rơi. Trả về null nếu thả ra cũng không đổi gì. */
  function locate(dragged: Active, over: Over | null): DropTarget | null {
    const from = origin.current
    if (!over || !from) return null
    const overId = String(over.id)
    const col = findContainer(overId)
    if (!col) return null
    let index = items[col].length // chỉ vào cột (cột trống) → rơi xuống cuối
    if (overId !== col) {
      // Chỉ vào một thẻ: con trỏ ở nửa trên → chèn TRƯỚC thẻ đó, nửa dưới → chèn SAU
      const rect = dragged.rect.current.translated
      const y = pointerY.current ?? (rect ? rect.top + rect.height / 2 : null)
      const below = y !== null && y > over.rect.top + over.rect.height / 2
      index = items[col].findIndex((t) => taskKey(t.id) === overId) + (below ? 1 : 0)
    }
    // Ngay trước hoặc ngay sau chính nó = không đổi chỗ → không hiện vạch
    if (col === from.col && (index === from.index || index === from.index + 1)) return null
    return { col, index }
  }

  function track({ active: dragged, over }: { active: Active; over: Over | null }) {
    const next = locate(dragged, over)
    const prev = targetRef.current
    if (prev?.col === next?.col && prev?.index === next?.index) return // chuột nhích nhưng chỗ thả không đổi
    targetRef.current = next
    setTarget(next)
  }

  function reset() {
    setActive(null)
    setTarget(null)
    targetRef.current = null
    lastOver.current = null
    origin.current = null
  }

  function onDragStart({ active: dragged }: DragStartEvent) {
    const id = String(dragged.id)
    const col = findContainer(id)
    if (!col) return
    const index = items[col].findIndex((t) => taskKey(t.id) === id)
    origin.current = { col, index }
    setActive(items[col][index])
  }

  function onDragEnd() {
    const from = origin.current
    const to = targetRef.current
    reset()
    if (!from || !to) return // thả ra ngoài / thả về chỗ cũ

    const moving = items[from.col][from.index]
    // `to.index` tính trên danh sách còn chứa thẻ đang kéo; rút thẻ ra thì các thẻ phía sau dồn lên 1
    const finalIndex = to.col === from.col && to.index > from.index ? to.index - 1 : to.index
    const next: Items = { ...items, [from.col]: items[from.col].filter((t) => t.id !== moving.id) }
    next[to.col] = [...next[to.col].slice(0, finalIndex), moving, ...next[to.col].slice(finalIndex)]
    setItems(next)

    const columnId = Number(to.col.slice(2))
    // Cập nhật cache ngay (optimistic) để bảng không "nhảy" về chỗ cũ
    qc.setQueryData<BoardDetail>(['board', board.id], (old) =>
      old && {
        ...old,
        columns: old.columns.map((c) => ({
          ...c,
          tasks: (next[colKey(c.id)] ?? []).map((t) => (t.id === moving.id ? { ...t, column_id: columnId } : t)),
        })),
      },
    )
    moveTask(moving.id, columnId, finalIndex)
      .catch((e) => alert(errorMessage(e, 'Không di chuyển được thẻ')))
      .finally(() => qc.invalidateQueries({ queryKey: ['board', board.id] }))
  }

  const dragDisabled = filterFn !== null
  // Các cột chưa hoàn thành, theo thứ tự → gán tông màu (cột hoàn thành luôn xanh lá)
  const openColumnIds = board.columns.filter((c) => !c.is_done).map((c) => c.id)

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={onDragStart}
      onDragMove={track}
      onDragOver={track}
      onDragEnd={onDragEnd}
      onDragCancel={reset}
    >
      <div className="flex items-start gap-3 self-stretch">
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
              toneIndex={openColumnIds.indexOf(c.id)}
              dropIndex={target?.col === colKey(c.id) ? target.index : null}
              canEdit={canEdit}
              onOpenTask={openTask}
            />
          )
        })}
      </div>
      {/* Bản sao của thẻ đi theo con trỏ khi kéo; thả ra thì trượt nhanh về chỗ mới */}
      <DragOverlay dropAnimation={{ duration: 180, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }}>
        {active && <TaskCardView task={active} done={false} dragging />}
      </DragOverlay>
    </DndContext>
  )
}
