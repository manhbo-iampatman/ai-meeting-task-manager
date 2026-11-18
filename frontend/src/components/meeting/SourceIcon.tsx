import { FileAudio, FileText, Mic, Video, type LucideIcon } from 'lucide-react'
import type { Meeting } from '../../api/types'

/** Bốn nguồn cuộc họp: mỗi nguồn một biểu tượng + màu riêng để nhìn lướt danh sách là phân biệt được. */
export const SOURCE: Record<Meeting['source_type'], { icon: LucideIcon; label: string; tone: string }> = {
  audio: { icon: FileAudio, label: 'Tải file ghi âm', tone: 'bg-sky-100 text-sky-700' },
  recording: { icon: Mic, label: 'Ghi trực tiếp', tone: 'bg-rose-100 text-rose-700' },
  text: { icon: FileText, label: 'Văn bản', tone: 'bg-amber-100 text-amber-700' },
  online: { icon: Video, label: 'Online Meeting', tone: 'bg-violet-100 text-violet-700' },
}

/** Ô biểu tượng của nguồn cuộc họp (dùng trong danh sách cuộc họp). */
export default function SourceIcon({ type }: { type: Meeting['source_type'] }) {
  const { icon: Icon, label, tone } = SOURCE[type] ?? SOURCE.audio
  return (
    <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${tone}`} title={label}>
      <Icon className="size-[18px]" aria-hidden="true" />
    </span>
  )
}

/** Biểu tượng + tên nguồn trên một dòng (dùng trong khung "Thông tin" của trang cuộc họp). */
export function SourceLabel({ type }: { type: Meeting['source_type'] }) {
  const { icon: Icon, label } = SOURCE[type] ?? SOURCE.audio
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon className="size-4 text-slate-500" aria-hidden="true" />
      {label}
    </span>
  )
}
