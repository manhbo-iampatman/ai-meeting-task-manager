import type { CSSProperties } from 'react'
import {
  VideoTrack,
  isTrackReference,
  useIsMuted,
  useIsSpeaking,
  useParticipantAttribute,
  type TrackReferenceOrPlaceholder,
} from '@livekit/components-react'
import { Track } from 'livekit-client'
import { Hand, MicOff, MonitorUp, Pin, PinOff } from 'lucide-react'
import { avatarColor, initialOf } from './layout'

export function trackKey(t: TrackReferenceOrPlaceholder) {
  return `${t.participant.identity}:${t.source}`
}

/**
 * Một ô trong phòng họp (kiểu Google Meet):
 * - có hình → video; tắt cam → vòng tròn màu có chữ cái đầu tên
 * - tên ở góc dưới trái, biểu tượng mic tắt ở góc trên phải, ✋ khi đang giơ tay
 * - đang nói → viền sáng (và vòng sáng quanh avatar)
 * - rê chuột / chạm vào ô → hiện nút ghim lên khung lớn
 */
export default function ParticipantCard({
  trackRef,
  pinned = false,
  onTogglePin,
  compact = false,
  className = '',
  style,
}: {
  trackRef: TrackReferenceOrPlaceholder
  pinned?: boolean
  onTogglePin?: () => void
  /** ô nhỏ (dải bên cạnh, ô nổi của mình): chữ / biểu tượng nhỏ hơn */
  compact?: boolean
  className?: string
  style?: CSSProperties
}) {
  const p = trackRef.participant
  const isScreen = trackRef.source === Track.Source.ScreenShare
  const name = p.name || p.identity
  const speaking = useIsSpeaking(p)
  const micMuted = useIsMuted({ participant: p, source: Track.Source.Microphone })
  const camMuted = useIsMuted(trackRef)
  const hand = useParticipantAttribute('hand', { participant: p })
  const showVideo = isTrackReference(trackRef) && !camMuted

  const label = isScreen ? (p.isLocal ? 'Bạn đang chia sẻ màn hình' : `Màn hình của ${name}`) : p.isLocal ? `${name} (bạn)` : name
  const ring = speaking && !isScreen ? 'ring-[3px] ring-brand-400' : 'ring-1 ring-white/5'

  return (
    <div
      // `relative` để định vị các nhãn bên trong; ô nổi (PiP) truyền `absolute` qua className thì bỏ `relative`
      // (hai class cùng đặt `position` thì class sinh SAU trong CSS thắng, không theo thứ tự viết)
      className={`group ${className.includes('absolute') ? '' : 'relative'} overflow-hidden rounded-2xl bg-[var(--room-tile)] outline-none transition-shadow duration-200 ${ring} ${className}`}
      style={style}
      tabIndex={onTogglePin ? 0 : undefined}
    >
      {showVideo ? (
        <VideoTrack
          trackRef={trackRef}
          className={`h-full w-full ${isScreen ? 'object-contain' : 'object-cover'}`}
          // Hình của chính mình lật như gương (giống Meet) — người khác vẫn thấy đúng chiều
          style={p.isLocal && !isScreen ? { transform: 'scaleX(-1)' } : undefined}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center">
          {isScreen ? (
            <MonitorUp className="size-10 text-white/40" aria-hidden="true" />
          ) : (
            <span
              className={`flex aspect-square items-center justify-center rounded-full font-semibold text-white transition-shadow duration-200 select-none ${
                speaking ? 'shadow-[0_0_0_6px_rgb(96_165_250/0.45)]' : ''
              }`}
              style={{
                width: compact ? '34%' : '26%',
                maxWidth: compact ? 72 : 128,
                minWidth: 36,
                background: avatarColor(p.identity),
                fontSize: compact ? 'clamp(0.9rem, 4vw, 1.6rem)' : 'clamp(1.2rem, 5vw, 3rem)',
              }}
              aria-hidden="true"
            >
              {initialOf(name)}
            </span>
          )}
        </div>
      )}

      {/* Góc trên trái: đang giơ tay */}
      {hand && !isScreen && (
        <span
          className={`absolute top-2 left-2 flex items-center gap-1 rounded-full bg-amber-400 px-2 py-0.5 font-medium text-black shadow ${compact ? 'text-[10px]' : 'text-xs'}`}
          title={`${name} đang giơ tay`}
        >
          <Hand className={compact ? 'size-3' : 'size-3.5'} aria-hidden="true" />
          {!compact && 'Giơ tay'}
        </span>
      )}

      {/* Góc trên phải: nút ghim (hiện khi rê chuột / chạm) + mic tắt */}
      <div className="absolute top-2 right-2 flex items-center gap-1.5">
        {onTogglePin && (
          <button
            type="button"
            onClick={onTogglePin}
            className={`flex size-8 items-center justify-center rounded-full bg-black/55 text-white transition hover:bg-black/75 focus-visible:opacity-100 ${
              pinned ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'
            }`}
            title={pinned ? 'Bỏ ghim' : 'Ghim lên khung lớn (chỉ trên máy bạn)'}
            aria-label={pinned ? `Bỏ ghim ${label}` : `Ghim ${label}`}
          >
            {pinned ? <PinOff className="size-4" aria-hidden="true" /> : <Pin className="size-4" aria-hidden="true" />}
          </button>
        )}
        {!isScreen && micMuted && (
          <span className="flex size-7 items-center justify-center rounded-full bg-black/55" title="Mic đang tắt">
            <MicOff className="size-3.5 text-white" aria-label="Mic đang tắt" />
          </span>
        )}
      </div>

      {/* Góc dưới trái: tên */}
      <span
        className={`absolute bottom-2 left-2 max-w-[calc(100%-1rem)] truncate rounded-md bg-black/45 px-2 py-0.5 font-medium text-white ${
          compact ? 'text-[11px]' : 'text-xs sm:text-sm'
        }`}
      >
        {isScreen && <MonitorUp className="mr-1 inline size-3.5 align-[-2px]" aria-hidden="true" />}
        {label}
      </span>
    </div>
  )
}
