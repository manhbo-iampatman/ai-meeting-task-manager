import { useState, type ReactNode } from 'react'
import { useParticipants } from '@livekit/components-react'
import { Track, type Participant } from 'livekit-client'
import { Check, Copy, Hand, Mic, MicOff, Pin, PinOff, X } from 'lucide-react'
import type { RecordingState, Room } from '../../api/types'
import { avatarColor, initialOf } from './layout'

export type PanelKind = 'people' | 'info'

/** Khung bên phải (máy tính) / tấm trượt từ dưới lên (điện thoại). */
export function PanelShell({
  title,
  narrow,
  onClose,
  children,
}: {
  title: string
  narrow: boolean
  onClose: () => void
  children: ReactNode
}) {
  const box = narrow
    ? 'fixed inset-x-0 bottom-0 z-20 max-h-[75dvh] rounded-t-3xl animate-pop'
    : 'my-2 mr-2 w-80 shrink-0 rounded-2xl animate-fade'
  return (
    <>
      {narrow && <div className="fixed inset-0 z-10 bg-black/50 animate-fade" onClick={onClose} aria-hidden="true" />}
      <aside className={`flex flex-col overflow-hidden bg-[var(--room-panel)] text-slate-800 shadow-2xl ${box}`} aria-label={title}>
        <div className="flex items-center justify-between px-4 pt-4 pb-2">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex size-9 items-center justify-center rounded-full text-slate-600 transition hover:bg-white/10"
            aria-label="Đóng"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{children}</div>
      </aside>
    </>
  )
}

function handTime(p: Participant): number {
  const v = p.attributes?.hand
  return v ? Number(v) || 1 : 0
}

/** Danh sách người tham gia: người đang giơ tay lên đầu (ai giơ trước đứng trước). */
export function PeoplePanel({
  room,
  pinned,
  onPin,
}: {
  room: Room
  pinned: string | null
  onPin: (key: string | null) => void
}) {
  const participants = useParticipants()
  const sorted = [...participants].sort((a, b) => {
    const ha = handTime(a)
    const hb = handTime(b)
    if (ha && hb) return ha - hb
    if (ha || hb) return ha ? -1 : 1
    return (a.joinedAt?.getTime() ?? 0) - (b.joinedAt?.getTime() ?? 0)
  })
  const raised = sorted.filter(handTime).length

  return (
    <>
      <p className="mb-3 text-xs text-slate-500">
        {participants.length}/6 người trong phòng
        {raised > 0 && ` · ${raised} người đang giơ tay`}
      </p>
      <ul className="space-y-1">
        {sorted.map((p) => {
          const key = `${p.identity}:${Track.Source.Camera}`
          const name = p.name || p.identity
          const isPinned = pinned === key
          return (
            <li key={p.identity} className="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-white/5">
              <span
                className="flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white"
                style={{ background: avatarColor(p.identity) }}
                aria-hidden="true"
              >
                {initialOf(name)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">
                  {name}
                  {p.isLocal && <span className="text-slate-500"> (bạn)</span>}
                </div>
                <div className="flex flex-wrap gap-1 empty:hidden">
                  {Number(p.identity) === room.host?.id && (
                    <span className="rounded bg-brand-500/30 px-1.5 text-[10px] text-brand-800">Chủ phòng</span>
                  )}
                  {Number(p.identity) === room.owner_id && (
                    <span className="rounded bg-amber-500/30 px-1.5 text-[10px] text-amber-800">Trưởng nhóm</span>
                  )}
                </div>
              </div>
              {handTime(p) > 0 && <Hand className="size-4 shrink-0 text-amber-400" aria-label="Đang giơ tay" />}
              <button
                type="button"
                onClick={() => onPin(isPinned ? null : key)}
                className={`flex size-8 shrink-0 items-center justify-center rounded-full transition hover:bg-white/10 ${
                  isPinned ? 'text-brand-600' : 'text-slate-500'
                }`}
                title={isPinned ? 'Bỏ ghim' : 'Ghim lên khung lớn (chỉ trên máy bạn)'}
                aria-label={isPinned ? `Bỏ ghim ${name}` : `Ghim ${name}`}
              >
                {isPinned ? <PinOff className="size-4" aria-hidden="true" /> : <Pin className="size-4" aria-hidden="true" />}
              </button>
              {p.isMicrophoneEnabled ? (
                <Mic className="size-4 shrink-0 text-emerald-600" aria-label="Mic đang bật" />
              ) : (
                <MicOff className="size-4 shrink-0 text-slate-500" aria-label="Mic đang tắt" />
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}

/** Thông tin buổi họp + link mời. */
export function InfoPanel({ room, recording }: { room: Room; recording: RecordingState }) {
  const link = `${window.location.origin}/room/${room.code}`
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-4 text-sm">
      <div>
        <p className="font-medium">{room.title}</p>
        <p className="text-slate-500">
          Nhóm {room.workspace_name}
          {room.host && ` · chủ phòng ${room.host.full_name}`}
        </p>
      </div>
      <div>
        <p className="mb-1.5 text-xs font-medium text-slate-600">Link tham gia</p>
        <p className="rounded-lg bg-white/5 px-3 py-2 font-mono text-xs break-all text-slate-700">{link}</p>
        <button
          type="button"
          className="mt-2 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-brand-600 transition hover:bg-brand-500/15"
          onClick={async () => {
            await navigator.clipboard.writeText(link)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
          {copied ? 'Đã chép link' : 'Chép link mời'}
        </button>
        <p className="mt-1 text-xs text-slate-500">
          Người nhận link đăng nhập (hoặc đăng ký) là vào được phòng và tự được thêm vào nhóm.
        </p>
      </div>
      <div className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-600">
        {recording === 'on' && 'Buổi họp đang được ghi âm để làm biên bản. Lời nói được ghi lại khi mic bật; tắt mic thì không ghi.'}
        {recording === 'idle' && 'Buổi họp chưa ghi âm. Chủ phòng hoặc trưởng nhóm bấm nút ghi âm để bắt đầu.'}
        {recording === 'stopped' && 'Đã dừng ghi âm. Phần đã ghi sẽ thành bản ghi khi buổi họp kết thúc.'}
      </div>
    </div>
  )
}
