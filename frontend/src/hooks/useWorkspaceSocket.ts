import { useQueryClient } from '@tanstack/react-query'
import type { Meeting, MeetingDetail } from '../api/types'
import { useRealtime } from './useRealtime'

type MeetingEvent = { type: string; meeting_id: number; status?: Meeting['status']; progress?: number }

/**
 * Theo dõi tiến độ xử lý cuộc họp của 1 nhóm (worker AI → Redis → backend → đây).
 *
 * - Sự kiện chỉ đổi % tiến độ → sửa thẳng vào cache (không gọi API) cho thanh tiến độ chạy mượt.
 * - Sự kiện đổi trạng thái (vd. xong / lỗi) → tải lại dữ liệu đầy đủ (có bản ghi văn bản).
 */
export function useWorkspaceSocket(workspaceId: number | undefined) {
  const qc = useQueryClient()
  return useRealtime(workspaceId ? `workspaces/${workspaceId}` : null, (raw) => {
    const msg = raw as MeetingEvent
    if (msg.type === 'meeting_deleted') {
      qc.invalidateQueries({ queryKey: ['meetings', workspaceId] })
      return
    }
    if (msg.type !== 'meeting_updated') return

    const patch = (m: Meeting) =>
      m.id === msg.meeting_id ? { ...m, status: msg.status ?? m.status, progress: msg.progress ?? m.progress } : m

    const cached = qc.getQueryData<MeetingDetail>(['meeting', msg.meeting_id])
    const statusChanged = !cached || cached.status !== msg.status

    qc.setQueryData<MeetingDetail>(['meeting', msg.meeting_id], (old) => old && { ...old, ...patch(old) })
    qc.setQueryData<Meeting[]>(['meetings', workspaceId], (old) => old?.map(patch))

    if (statusChanged) {
      qc.invalidateQueries({ queryKey: ['meeting', msg.meeting_id] })
      qc.invalidateQueries({ queryKey: ['meetings', workspaceId] })
    }
  })
}
