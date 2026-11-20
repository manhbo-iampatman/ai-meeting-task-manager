import { useEffect, useRef, useState, type ReactNode } from 'react'
import { MediaDeviceMenu, useTrackToggle } from '@livekit/components-react'
import { Track } from 'livekit-client'
import {
  ChevronUp,
  Circle,
  EllipsisVertical,
  Hand,
  Info,
  Mic,
  MicOff,
  MonitorOff,
  MonitorUp,
  PhoneOff,
  Square,
  Users,
  Video,
  VideoOff,
} from 'lucide-react'
import type { RecordingState, Room } from '../../api/types'
import type { PanelKind } from './RoomPanels'
import { useClock } from './layout'

/** Chia sẻ màn hình chỉ có trên trình duyệt máy tính (điện thoại không có getDisplayMedia). */
export const CAN_SHARE_SCREEN = typeof navigator.mediaDevices?.getDisplayMedia === 'function'

/** Nút tròn kiểu Meet. `danger` = trạng thái tắt (mic / cam đang tắt → nền đỏ). */
function RoundButton({
  label,
  active = false,
  danger = false,
  disabled,
  onClick,
  children,
  className = '',
}: {
  label: string
  active?: boolean
  danger?: boolean
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
  className?: string
}) {
  const tone = danger
    ? 'bg-rose-500 text-white hover:bg-rose-400'
    : active
      ? 'bg-brand-300 text-white hover:bg-brand-200'
      : 'bg-[var(--room-button)] text-white hover:bg-[var(--room-button-hover)]'
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active || undefined}
      disabled={disabled}
      onClick={onClick}
      className={`relative flex size-11 shrink-0 items-center justify-center rounded-full transition disabled:opacity-50 sm:size-12 ${tone} ${className}`}
    >
      {children}
    </button>
  )
}

/** Mic / camera / màn hình: bấm để bật / tắt (LiveKit lo phần thiết bị). */
function MediaToggle({
  source,
  narrow,
}: {
  source: Track.Source.Microphone | Track.Source.Camera | Track.Source.ScreenShare
  narrow: boolean
}) {
  const isScreen = source === Track.Source.ScreenShare
  const { enabled, pending, toggle } = useTrackToggle({
    source,
    captureOptions: isScreen ? { audio: false, selfBrowserSurface: 'include' } : undefined,
  })
  const label =
    source === Track.Source.Microphone
      ? enabled
        ? 'Tắt mic'
        : 'Bật mic'
      : source === Track.Source.Camera
        ? enabled
          ? 'Tắt camera'
          : 'Bật camera'
        : enabled
          ? 'Dừng chia sẻ màn hình'
          : 'Chia sẻ màn hình'
  const icon =
    source === Track.Source.Microphone ? (
      enabled ? <Mic className="size-5" /> : <MicOff className="size-5" />
    ) : source === Track.Source.Camera ? (
      enabled ? <Video className="size-5" /> : <VideoOff className="size-5" />
    ) : enabled ? (
      <MonitorOff className="size-5" />
    ) : (
      <MonitorUp className="size-5" />
    )
  const button = (
    <RoundButton label={label} danger={!isScreen && !enabled} active={isScreen && enabled} disabled={pending} onClick={() => void toggle()}>
      {icon}
    </RoundButton>
  )
  if (isScreen || narrow) return button
  // Máy tính: mũi tên nhỏ cạnh nút để chọn mic / camera khác (như Meet)
  return (
    <div className="flex items-center rounded-full bg-[var(--room-button)]/60 pr-0.5">
      <div className="mf-device-menu">
        <MediaDeviceMenu kind={source === Track.Source.Microphone ? 'audioinput' : 'videoinput'} title="Chọn thiết bị">
          <ChevronUp className="size-4" aria-hidden="true" />
        </MediaDeviceMenu>
      </div>
      {button}
    </div>
  )
}

/** Menu nhỏ bật lên phía trên nút (đóng khi bấm ra ngoài). */
function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close()
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, close])
  return ref
}

export type ControlActions = {
  room: Room
  recording: RecordingState
  handRaised: boolean
  onToggleHand: () => void
  onStartRecording: () => void
  onStopRecording: () => void
  onEndForAll: () => void
  onLeave: () => void
  busy: boolean
  panel: PanelKind | null
  onPanel: (p: PanelKind | null) => void
  participantCount: number
  raisedCount: number
}

function RecordButton({ recording, onStart, onStop, busy }: { recording: RecordingState; onStart: () => void; onStop: () => void; busy: boolean }) {
  if (recording === 'on') {
    return (
      <RoundButton label="Dừng ghi âm" danger disabled={busy} onClick={onStop}>
        <Square className="size-4 fill-current" aria-hidden="true" />
      </RoundButton>
    )
  }
  if (recording === 'idle') {
    return (
      <RoundButton label="Bắt đầu ghi âm" disabled={busy} onClick={onStart}>
        <Circle className="size-5 fill-rose-500 text-rose-500" aria-hidden="true" />
      </RoundButton>
    )
  }
  return null // đã dừng ghi: buổi này không ghi tiếp được nữa
}

/** Nút đỏ rời phòng. Chủ phòng / trưởng nhóm có thêm mũi tên: "Kết thúc cho mọi người". */
function LeaveButton({ canControl, onLeave, onEndForAll, busy }: { canControl: boolean; onLeave: () => void; onEndForAll: () => void; busy: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useOutsideClose(open, () => setOpen(false))
  return (
    <div ref={ref} className="relative flex">
      <button
        type="button"
        onClick={onLeave}
        title="Rời phòng"
        aria-label="Rời phòng"
        className={`flex h-11 items-center justify-center bg-rose-500 px-5 text-white transition hover:bg-rose-400 sm:h-12 sm:px-6 ${
          canControl ? 'rounded-l-full pr-3 sm:pr-4' : 'rounded-full'
        }`}
      >
        <PhoneOff className="size-5" aria-hidden="true" />
      </button>
      {canControl && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          title="Tùy chọn kết thúc"
          aria-label="Tùy chọn kết thúc"
          aria-expanded={open}
          className="flex h-11 items-center rounded-r-full border-l border-black/20 bg-rose-500 px-2 text-white transition hover:bg-rose-400 sm:h-12"
        >
          <ChevronUp className={`size-4 transition-transform ${open ? '' : 'rotate-180'}`} aria-hidden="true" />
        </button>
      )}
      {open && (
        <div className="absolute right-0 bottom-full z-30 mb-2 w-64 animate-pop overflow-hidden rounded-xl bg-[var(--room-panel)] py-1 text-sm text-slate-800 shadow-2xl">
          <button type="button" className="w-full px-4 py-2.5 text-left hover:bg-white/5" onClick={() => (setOpen(false), onLeave())}>
            Rời phòng
          </button>
          <button
            type="button"
            disabled={busy}
            className="w-full px-4 py-2.5 text-left text-rose-600 hover:bg-white/5 disabled:opacity-50"
            onClick={() => (setOpen(false), onEndForAll())}
          >
            Kết thúc cuộc họp cho mọi người
          </button>
        </div>
      )}
    </div>
  )
}

function HandButton({ raised, onToggle }: { raised: boolean; onToggle: () => void }) {
  return (
    <RoundButton label={raised ? 'Hạ tay' : 'Giơ tay'} active={raised} onClick={onToggle} className={raised ? '!bg-amber-400 !text-black' : ''}>
      <Hand className="size-5" aria-hidden="true" />
    </RoundButton>
  )
}

function Badge({ n, tone = 'bg-brand-500' }: { n: number; tone?: string }) {
  if (n <= 0) return null
  return (
    <span className={`absolute -top-0.5 -right-0.5 min-w-5 rounded-full px-1 text-center text-[11px] leading-5 font-semibold text-white ${tone}`}>
      {n}
    </span>
  )
}

/** Thanh nút dưới đáy — máy tính: [giờ | tên phòng]  [nút giữa]  [thông tin, người]. */
export function DesktopControls(a: ControlActions) {
  const clock = useClock()
  const toggle = (p: PanelKind) => a.onPanel(a.panel === p ? null : p)
  return (
    <div className="grid shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-4 px-4 pt-1 pb-3">
      <div className="min-w-0 truncate text-sm text-white/90">
        <span className="font-medium">{clock}</span>
        <span className="mx-2 text-white/40">|</span>
        <span className="text-white/80">{a.room.title}</span>
      </div>
      <div className="flex items-center gap-2.5">
        <MediaToggle source={Track.Source.Microphone} narrow={false} />
        <MediaToggle source={Track.Source.Camera} narrow={false} />
        {CAN_SHARE_SCREEN && <MediaToggle source={Track.Source.ScreenShare} narrow={false} />}
        <HandButton raised={a.handRaised} onToggle={a.onToggleHand} />
        {a.room.can_control && (
          <RecordButton recording={a.recording} onStart={a.onStartRecording} onStop={a.onStopRecording} busy={a.busy} />
        )}
        <LeaveButton canControl={a.room.can_control} onLeave={a.onLeave} onEndForAll={a.onEndForAll} busy={a.busy} />
      </div>
      <div className="flex items-center justify-end gap-1">
        <RoundButton label="Thông tin buổi họp" active={a.panel === 'info'} onClick={() => toggle('info')} className="!bg-transparent hover:!bg-white/10">
          <Info className="size-5" aria-hidden="true" />
        </RoundButton>
        <RoundButton
          label={`Người tham gia (${a.participantCount})`}
          active={a.panel === 'people'}
          onClick={() => toggle('people')}
          className="!bg-transparent hover:!bg-white/10"
        >
          <Users className="size-5" aria-hidden="true" />
          <Badge n={a.raisedCount > 0 ? a.raisedCount : a.participantCount} tone={a.raisedCount > 0 ? 'bg-amber-500' : 'bg-white/25'} />
        </RoundButton>
      </div>
    </div>
  )
}

/** Thanh nút dưới đáy — điện thoại: mic, cam, giơ tay, ⋯ (người, thông tin, ghi âm, kết thúc), rời phòng. */
export function MobileControls(a: ControlActions) {
  const [sheet, setSheet] = useState(false)
  const item = 'flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm hover:bg-white/5 disabled:opacity-50'
  return (
    <>
      <div className="flex shrink-0 items-center justify-center gap-2.5 px-3 pt-1 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <MediaToggle source={Track.Source.Microphone} narrow />
        <MediaToggle source={Track.Source.Camera} narrow />
        <HandButton raised={a.handRaised} onToggle={a.onToggleHand} />
        <RoundButton label="Thêm tùy chọn" onClick={() => setSheet(true)}>
          <EllipsisVertical className="size-5" aria-hidden="true" />
          <Badge n={a.raisedCount} tone="bg-amber-500" />
        </RoundButton>
        <LeaveButton canControl={false} onLeave={a.onLeave} onEndForAll={a.onEndForAll} busy={a.busy} />
      </div>
      {sheet && (
        <>
          <div className="fixed inset-0 z-10 bg-black/50 animate-fade" onClick={() => setSheet(false)} aria-hidden="true" />
          <div className="fixed inset-x-0 bottom-0 z-20 animate-pop rounded-t-3xl bg-[var(--room-panel)] p-3 pb-[max(1rem,env(safe-area-inset-bottom))] text-slate-800 shadow-2xl">
            <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-slate-300" aria-hidden="true" />
            <button type="button" className={item} onClick={() => (setSheet(false), a.onPanel('people'))}>
              <Users className="size-5 text-slate-600" aria-hidden="true" />
              Người tham gia ({a.participantCount}){a.raisedCount > 0 && <span className="text-amber-600"> · {a.raisedCount} giơ tay</span>}
            </button>
            <button type="button" className={item} onClick={() => (setSheet(false), a.onPanel('info'))}>
              <Info className="size-5 text-slate-600" aria-hidden="true" />
              Thông tin & link mời
            </button>
            {a.room.can_control && a.recording === 'idle' && (
              <button type="button" className={item} disabled={a.busy} onClick={() => (setSheet(false), a.onStartRecording())}>
                <Circle className="size-5 fill-rose-500 text-rose-500" aria-hidden="true" />
                Bắt đầu ghi âm
              </button>
            )}
            {a.room.can_control && a.recording === 'on' && (
              <button type="button" className={item} disabled={a.busy} onClick={() => (setSheet(false), a.onStopRecording())}>
                <Square className="size-5 fill-current text-rose-600" aria-hidden="true" />
                Dừng ghi âm
              </button>
            )}
            {a.room.can_control && (
              <button type="button" className={`${item} text-rose-600`} disabled={a.busy} onClick={() => (setSheet(false), a.onEndForAll())}>
                <PhoneOff className="size-5" aria-hidden="true" />
                Kết thúc cuộc họp cho mọi người
              </button>
            )}
          </div>
        </>
      )}
    </>
  )
}
