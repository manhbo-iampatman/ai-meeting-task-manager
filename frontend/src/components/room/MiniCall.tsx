import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSpeakingParticipants, useTrackToggle, useTracks } from '@livekit/components-react'
import { Track } from 'livekit-client'
import { Maximize2, Mic, MicOff, PhoneOff } from 'lucide-react'
import type { RecordingState, Room } from '../../api/types'
import { useCall, type MiniPos } from '../../stores/call'
import ParticipantCard from './ParticipantCard'

const DEFAULT_POS: MiniPos = { right: 16, bottom: 16 }
const EDGE = 8 // luôn chừa 8px tới mép màn hình
const DRAG_THRESHOLD = 6 // kéo quá 6px mới tính là kéo (ít hơn = chạm / bấm)

/** Giữ ô nằm trọn trong màn hình (kéo ra ngoài, xoay ngang điện thoại, thu nhỏ cửa sổ…). */
function clampPos(p: MiniPos, el: HTMLElement | null): MiniPos {
  const w = el?.offsetWidth ?? 0
  const h = el?.offsetHeight ?? 0
  return {
    right: Math.min(Math.max(p.right, EDGE), Math.max(EDGE, window.innerWidth - w - EDGE)),
    bottom: Math.min(Math.max(p.bottom, EDGE), Math.max(EDGE, window.innerHeight - h - EDGE)),
  }
}

/**
 * Cuộc họp thu nhỏ (phương án B): ô nổi ở góc khi đang xem trang khác của MeetFlow.
 *
 * - Hiện người đang nói (ưu tiên màn hình người khác đang chia sẻ), chấm đỏ khi phòng đang ghi âm.
 * - Nút: bật / tắt mic, rời phòng, phóng to lại. Chạm vào hình cũng phóng to lại.
 * - Kéo đi chỗ khác được (chuột hoặc ngón tay); trên điện thoại ô nhỏ hơn.
 */
export default function MiniCall({
  room,
  recording,
  recorderError,
  narrow,
  onLeave,
}: {
  room: Room
  recording: RecordingState
  recorderError: boolean
  narrow: boolean
  onLeave: () => void
}) {
  const navigate = useNavigate()
  const expand = () => navigate(`/room/${room.code}`)

  // ---- Chọn hình để hiện ----
  const tracks = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true },
      { source: Track.Source.ScreenShare, withPlaceholder: false },
    ],
    { onlySubscribed: false },
  )
  const speakers = useSpeakingParticipants()
  const remoteSpeaker = speakers.find((p) => !p.isLocal)?.identity
  // Nhớ người (khác mình) nói gần nhất → im lặng một lúc thì ô vẫn hiện người đó, không nhảy lung tung
  const [lastSpeaker, setLastSpeaker] = useState<string | null>(null)
  if (remoteSpeaker && remoteSpeaker !== lastSpeaker) setLastSpeaker(remoteSpeaker) // cập nhật ngay trong lúc vẽ (cách React khuyên)

  const remoteCams = tracks.filter((t) => t.source === Track.Source.Camera && !t.participant.isLocal)
  const focus =
    tracks.find((t) => t.source === Track.Source.ScreenShare && !t.participant.isLocal) ??
    remoteCams.find((t) => t.participant.identity === lastSpeaker) ??
    remoteCams[0] ??
    tracks.find((t) => t.source === Track.Source.Camera && t.participant.isLocal)

  // ---- Kéo thả ----
  const boxRef = useRef<HTMLDivElement>(null)
  const pos = useCall((s) => s.miniPos) ?? DEFAULT_POS
  const setPos = useCall((s) => s.setMiniPos)
  const drag = useRef<{ id: number; x: number; y: number; start: MiniPos; moved: boolean } | null>(null)
  const justDragged = useRef(false)

  useEffect(() => {
    const fit = () => setPos(clampPos(useCall.getState().miniPos ?? DEFAULT_POS, boxRef.current))
    fit() // ô vừa hiện (cỡ có thể khác lần trước: máy tính ↔ điện thoại) → đặt lại cho vừa màn hình
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [setPos, narrow])

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    justDragged.current = false
    if (e.button !== 0 || (e.target as HTMLElement).closest('[data-no-drag]')) return
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, start: pos, moved: false }
  }
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    if (!d.moved) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return
      d.moved = true
      // Chỉ "giữ" con trỏ khi đã thật sự kéo — nếu giữ ngay từ lúc nhấn, cú chạm vào hình không còn là cú bấm
      e.currentTarget.setPointerCapture(e.pointerId)
    }
    setPos(clampPos({ right: d.start.right - dx, bottom: d.start.bottom - dy }, boxRef.current))
  }
  const onPointerEnd = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    if (d.moved) justDragged.current = true // vừa kéo xong → bỏ qua cú "bấm" đi kèm
  }

  const btn = narrow ? 'size-9' : 'size-10'
  const icon = narrow ? 'size-4' : 'size-[18px]'

  return (
    <div
      ref={boxRef}
      role="region"
      aria-label={`Cuộc họp đang diễn ra: ${room.title}`}
      className={`fixed z-40 flex touch-none flex-col overflow-hidden rounded-2xl bg-[var(--room-panel)] text-white shadow-2xl ring-1 ring-white/10 select-none animate-pop ${
        narrow ? 'w-44' : 'w-72'
      } cursor-grab active:cursor-grabbing`}
      style={{ right: pos.right, bottom: pos.bottom }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      onClickCapture={(e) => {
        if (justDragged.current) {
          justDragged.current = false
          e.stopPropagation()
          e.preventDefault()
        }
      }}
    >
      {/* Thanh trên: chấm ghi âm + tên phòng + phóng to */}
      <div className={`flex items-center gap-1.5 pr-1 pl-2.5 ${narrow ? 'py-1 text-[11px]' : 'py-1.5 text-xs'}`}>
        {recording === 'on' && (
          <span
            className={`size-2 shrink-0 animate-pulse rounded-full ${recorderError ? 'bg-amber-400' : 'bg-rose-500'}`}
            title={recorderError ? 'Phòng đang ghi âm nhưng không ghi được mic của bạn' : 'Phòng đang ghi âm'}
            aria-label={recorderError ? 'Phòng đang ghi âm nhưng không ghi được mic của bạn' : 'Phòng đang ghi âm'}
          />
        )}
        <span className="min-w-0 flex-1 truncate font-medium text-white/90">{room.title}</span>
        <button
          type="button"
          data-no-drag
          onClick={expand}
          className="flex size-7 shrink-0 items-center justify-center rounded-full text-white/80 transition hover:bg-white/10 hover:text-white"
          title="Mở lại cuộc họp"
          aria-label="Mở lại cuộc họp toàn màn hình"
        >
          <Maximize2 className="size-4" aria-hidden="true" />
        </button>
      </div>

      {/* Hình người đang nói — chạm để mở lại */}
      <div
        className="mx-1.5 aspect-video cursor-pointer"
        onClick={expand}
        title="Mở lại cuộc họp"
      >
        {focus && <ParticipantCard trackRef={focus} compact className="h-full w-full" />}
      </div>

      {/* Nút */}
      <div className={`flex items-center justify-center gap-2 ${narrow ? 'py-1.5' : 'py-2'}`}>
        <MiniMicButton className={btn} iconClass={icon} />
        <button
          type="button"
          data-no-drag
          onClick={onLeave}
          className={`flex items-center justify-center rounded-full bg-rose-500 text-white transition hover:bg-rose-400 ${btn}`}
          title="Rời phòng"
          aria-label="Rời phòng"
        >
          <PhoneOff className={icon} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}

function MiniMicButton({ className, iconClass }: { className: string; iconClass: string }) {
  const { toggle, enabled, pending } = useTrackToggle({ source: Track.Source.Microphone })
  const label = enabled ? 'Tắt mic' : 'Bật mic'
  return (
    <button
      type="button"
      data-no-drag
      disabled={pending}
      onClick={() => void toggle()}
      className={`flex items-center justify-center rounded-full text-white transition disabled:opacity-50 ${
        enabled ? 'bg-[var(--room-button)] hover:bg-[var(--room-button-hover)]' : 'bg-rose-500 hover:bg-rose-400'
      } ${className}`}
      title={label}
      aria-label={label}
      aria-pressed={!enabled}
    >
      {enabled ? <Mic className={iconClass} aria-hidden="true" /> : <MicOff className={iconClass} aria-hidden="true" />}
    </button>
  )
}
