import type { Task } from '../api/types'

/**
 * Ai được kéo thả / sửa / xóa một thẻ (quyết định 18/11/2026, khớp `can_edit_task` ở backend):
 * người làm, người tạo thẻ, trưởng nhóm. Thành viên khác chỉ xem + bình luận.
 * Thẻ chưa có người làm hoặc giao theo tên chữ → chỉ người tạo thẻ + trưởng nhóm.
 */
export function canEditTask(task: Pick<Task, 'assignee' | 'created_by'>, ownerId: number | null | undefined, meId: number): boolean {
  return meId === ownerId || task.assignee?.id === meId || task.created_by === meId
}

export const NO_EDIT_REASON = 'Chỉ người làm, người tạo thẻ hoặc trưởng nhóm được kéo / sửa / xóa thẻ này'
