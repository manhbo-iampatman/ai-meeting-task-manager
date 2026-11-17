import { useQueryClient } from '@tanstack/react-query'
import { useRealtime } from './useRealtime'

/**
 * Theo dõi 1 bảng Kanban. Khi server báo có thay đổi (người khác thêm / kéo / sửa thẻ),
 * đánh dấu dữ liệu cũ → React Query tự tải lại.
 */
export function useBoardSocket(boardId: number) {
  const qc = useQueryClient()
  return useRealtime(boardId ? `boards/${boardId}` : null, (msg) => {
    if (msg.type === 'board_updated' || msg.type === 'board_deleted') {
      qc.invalidateQueries({ queryKey: ['board', boardId] })
      qc.invalidateQueries({ queryKey: ['task'] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
    }
  })
}
