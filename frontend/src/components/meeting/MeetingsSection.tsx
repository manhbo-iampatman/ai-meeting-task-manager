import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listMeetings } from '../../api/endpoints'
import { useWorkspaceSocket } from '../../hooks/useWorkspaceSocket'
import { formatClock, formatDate } from '../../lib/utils'
import { Button } from '../ui'
import MeetingStatusBadge from './MeetingStatusBadge'
import OnlineMeetingButton from './OnlineMeetingButton'
import PendingRecordings from './PendingRecordings'
import RecordMeetingModal from './RecordMeetingModal'
import UploadMeetingModal from './UploadMeetingModal'

export const SOURCE_ICON = { audio: '🎙️', recording: '🔴', text: '📝', online: '📹' } as const

/** Khối "Cuộc họp" trong trang nhóm: danh sách + nút thêm. Trạng thái cập nhật realtime. */
export default function MeetingsSection({ workspaceId }: { workspaceId: number }) {
  const [open, setOpen] = useState(false)
  const [recording, setRecording] = useState(false)
  const { data: meetings, isLoading } = useQuery({
    queryKey: ['meetings', workspaceId],
    queryFn: () => listMeetings(workspaceId),
  })
  useWorkspaceSocket(workspaceId)

  return (
    <section className="mt-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Cuộc họp</h2>
        <div className="flex flex-wrap justify-end gap-2">
          <OnlineMeetingButton workspaceId={workspaceId} />
          <Button variant="danger" onClick={() => setRecording(true)}>
            ● Ghi âm trực tiếp
          </Button>
          <Button variant="secondary" onClick={() => setOpen(true)}>
            ⬆ Tải file lên
          </Button>
        </div>
      </div>

      {/* Bản ghi còn trong trình duyệt (ẩn khi đang ghi để không hiện chính bản đang ghi) */}
      {!recording && <PendingRecordings workspaceId={workspaceId} />}

      {isLoading && <p className="text-sm text-slate-500">Đang tải…</p>}
      {meetings?.length === 0 && (
        <button
          onClick={() => setOpen(true)}
          className="w-full rounded-xl border-2 border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 hover:border-indigo-300 hover:text-indigo-600"
        >
          Chưa có cuộc họp nào. Họp ngay bằng <b>Online Meeting</b>, <b>ghi âm trực tiếp</b> hoặc <b>tải file ghi âm lên</b> để AI
          chuyển thành văn bản.
        </button>
      )}

      {meetings && meetings.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
          {meetings.map((m) => (
            <li key={m.id}>
              <Link to={`/meetings/${m.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-slate-50">
                <span className="text-lg">{SOURCE_ICON[m.source_type]}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{m.title}</div>
                  <div className="text-xs text-slate-500">
                    {formatDate(m.meeting_date)}
                    {m.duration_sec != null && ` · ${formatClock(m.duration_sec)}`}
                  </div>
                </div>
                <MeetingStatusBadge status={m.status} progress={m.progress} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {open && <UploadMeetingModal workspaceId={workspaceId} onClose={() => setOpen(false)} />}
      {recording && <RecordMeetingModal workspaceId={workspaceId} onClose={() => setRecording(false)} />}
    </section>
  )
}
