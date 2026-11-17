import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { deleteRecording, listRecordings, type RecordingMeta } from '../../lib/recordingStore'
import { uploadRecording } from '../../lib/uploadRecording'
import { formatClock, formatDate } from '../../lib/utils'
import { Button } from '../ui'

/**
 * Các bản ghi âm còn nằm trong trình duyệt, chưa lên server:
 *  - ghi xong nhưng tải lên lỗi (mất mạng...)
 *  - đang ghi thì trang bị đóng / sập (status vẫn là "recording")
 * Có mạng lại (sự kiện `online`) → tự tải lên.
 */
export default function PendingRecordings({ workspaceId }: { workspaceId: number }) {
  const qc = useQueryClient()
  const { data: items = [] } = useQuery({
    queryKey: ['pending-recordings', workspaceId],
    queryFn: () => listRecordings(workspaceId),
  })
  const [busy, setBusy] = useState<Record<string, number | undefined>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const uploading = useRef(new Set<string>())

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['pending-recordings', workspaceId] })
    qc.invalidateQueries({ queryKey: ['meetings', workspaceId] })
  }

  async function upload(r: RecordingMeta) {
    if (uploading.current.has(r.id)) return
    uploading.current.add(r.id)
    setErrors((e) => ({ ...e, [r.id]: '' }))
    setBusy((b) => ({ ...b, [r.id]: 0 }))
    try {
      await uploadRecording(r, (pct) => setBusy((b) => ({ ...b, [r.id]: pct })))
    } catch (e) {
      setErrors((x) => ({ ...x, [r.id]: (e as Error).message }))
    } finally {
      uploading.current.delete(r.id)
      setBusy((b) => ({ ...b, [r.id]: undefined }))
      refresh()
    }
  }

  // Có mạng lại → tự tải lên các bản ghi đã ghi xong
  useEffect(() => {
    const onOnline = () => items.filter((r) => r.status === 'ready').forEach((r) => void upload(r))
    window.addEventListener('online', onOnline)
    return () => window.removeEventListener('online', onOnline)
  }) // chạy lại mỗi lần render để luôn dùng danh sách mới nhất

  if (items.length === 0) return null

  return (
    <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
      <p className="mb-2 text-sm font-medium text-amber-800">⚠️ Bản ghi âm chưa tải lên ({items.length}) — đang lưu trên máy này</p>
      <ul className="space-y-2">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm">
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{r.title}</div>
              <div className="text-xs text-slate-500">
                {formatDate(r.meetingDate)} · {formatClock(r.durationSec)}
                {r.status === 'recording' && ' · bị gián đoạn khi đang ghi (vẫn dùng được phần đã ghi)'}
              </div>
              {(errors[r.id] || r.lastError) && <div className="text-xs text-rose-600">{errors[r.id] || r.lastError}</div>}
            </div>
            {busy[r.id] !== undefined ? (
              <span className="text-xs text-indigo-600">Đang tải lên… {busy[r.id]}%</span>
            ) : (
              <>
                <Button onClick={() => upload(r)}>Tải lên</Button>
                <Button
                  variant="ghost"
                  className="!text-rose-600"
                  onClick={async () => {
                    if (confirm(`Xóa vĩnh viễn bản ghi “${r.title}”? Không thể khôi phục.`)) {
                      await deleteRecording(r.id)
                      refresh()
                    }
                  }}
                >
                  Xóa
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
