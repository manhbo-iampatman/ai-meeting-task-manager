import { createMeeting } from '../api/endpoints'
import type { MeetingDetail } from '../api/types'
import { deleteRecording, extForMime, getRecordingBlob, saveMeta, type RecordingMeta } from './recordingStore'
import { errorMessage } from './utils'

/**
 * Tải 1 bản ghi đang lưu tạm trong trình duyệt lên server.
 * CHỈ xóa bản tạm khi server đã nhận thành công → mất mạng giữa chừng không mất dữ liệu.
 */
export async function uploadRecording(meta: RecordingMeta, onProgress?: (pct: number) => void): Promise<MeetingDetail> {
  const blob = await getRecordingBlob(meta)
  if (blob.size === 0) {
    await deleteRecording(meta.id)
    throw new Error('Bản ghi trống (chưa ghi được âm thanh nào)')
  }
  const stamp = new Date(meta.startedAt).toISOString().slice(0, 16).replace(/[-:T]/g, '')
  const file = new File([blob], `ghi-am-${stamp}${extForMime(meta.mimeType)}`, { type: meta.mimeType })
  try {
    const m = await createMeeting(
      meta.workspaceId,
      { title: meta.title, meeting_date: meta.meetingDate, file, recorded: true },
      onProgress,
    )
    await deleteRecording(meta.id)
    return m
  } catch (err) {
    const msg = !navigator.onLine ? 'Mất kết nối mạng — sẽ tự tải lên khi có mạng lại' : errorMessage(err, 'Tải lên thất bại')
    await saveMeta({ ...meta, status: 'ready', lastError: msg })
    throw new Error(msg, { cause: err })
  }
}
