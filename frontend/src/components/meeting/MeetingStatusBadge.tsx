import type { MeetingStatus } from '../../api/types'

export const STATUS_INFO: Record<MeetingStatus, { label: string; className: string }> = {
  uploaded: { label: 'Đã tải lên', className: 'bg-slate-100 text-slate-600' },
  queued: { label: 'Đang chờ xử lý', className: 'bg-amber-100 text-amber-700' },
  transcribing: { label: 'Đang chuyển giọng nói', className: 'bg-sky-100 text-sky-700' },
  transcribed: { label: 'Đã có bản ghi', className: 'bg-emerald-100 text-emerald-700' },
  failed: { label: 'Lỗi', className: 'bg-rose-100 text-rose-700' },
}

export default function MeetingStatusBadge({ status, progress }: { status: MeetingStatus; progress?: number }) {
  const info = STATUS_INFO[status] ?? STATUS_INFO.uploaded
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${info.className}`}>
      {(status === 'queued' || status === 'transcribing') && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {info.label}
      {status === 'transcribing' && progress != null && progress > 0 && ` · ${progress}%`}
    </span>
  )
}
