import { isTrackReference, useTracks, type TrackReferenceOrPlaceholder } from '@livekit/components-react'
import { RoomEvent, Track } from 'livekit-client'
import ParticipantCard, { trackKey } from './ParticipantCard'
import { fitGrid, useElementSize } from './layout'

const GAP = 8

/**
 * Khung hình chính của phòng họp, bố trí như Google Meet:
 *
 *   có màn hình chia sẻ / có người được ghim → khung lớn + dải ô người (bên phải; điện thoại: phía dưới)
 *   đúng 2 người                             → người kia to cả khung, ô của mình nổi nhỏ ở góc
 *   còn lại                                  → lưới tự chia vừa khung, KHÔNG phải cuộn
 */
export default function MeetingStage({
  pinned,
  onPin,
  narrow,
}: {
  pinned: string | null
  onPin: (key: string | null) => void
  narrow: boolean
}) {
  const tracks = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true }, // tắt cam vẫn có ô (avatar)
      { source: Track.Source.ScreenShare, withPlaceholder: false },
    ],
    { updateOnlyOn: [RoomEvent.ActiveSpeakersChanged], onlySubscribed: false },
  )
  const [ref, size] = useElementSize<HTMLDivElement>()

  // Người khác trước (theo thứ tự vào phòng), mình cuối — giống Meet
  const cams = tracks
    .filter((t) => t.source === Track.Source.Camera)
    .sort((a, b) => Number(a.participant.isLocal) - Number(b.participant.isLocal))
  const screens = tracks.filter((t) => isTrackReference(t) && t.source === Track.Source.ScreenShare)

  const pinnedTrack = pinned ? tracks.find((t) => trackKey(t) === pinned) : undefined
  const focus = pinnedTrack ?? screens[screens.length - 1] // người chia sẻ sau cùng lên khung lớn
  const togglePin = (t: TrackReferenceOrPlaceholder) => () => onPin(pinned === trackKey(t) ? null : trackKey(t))

  // Điện thoại dựng đứng → ô cao (3:4); máy tính → ô 16:9
  const portrait = size.height > size.width
  const aspect = portrait ? 3 / 4 : 16 / 9

  let body
  if (focus) {
    const others = tracks.filter((t) => t !== focus)
    const stripVertical = !narrow && !portrait
    body = (
      <div className={`flex h-full w-full gap-2 ${stripVertical ? 'flex-row' : 'flex-col'}`}>
        <ParticipantCard
          trackRef={focus}
          pinned={focus === pinnedTrack}
          onTogglePin={togglePin(focus)}
          className="min-h-0 min-w-0 flex-1"
        />
        {others.length > 0 && (
          <div
            className={
              stripVertical
                ? 'flex w-52 shrink-0 flex-col gap-2 overflow-y-auto pr-0.5 xl:w-60'
                : 'flex h-28 shrink-0 gap-2 overflow-x-auto pb-0.5 sm:h-32'
            }
          >
            {others.map((t) => (
              <ParticipantCard
                key={trackKey(t)}
                trackRef={t}
                compact
                onTogglePin={togglePin(t)}
                className={stripVertical ? 'aspect-video w-full shrink-0' : 'aspect-[4/3] h-full shrink-0'}
              />
            ))}
          </div>
        )}
      </div>
    )
  } else if (cams.length === 2) {
    const [other, me] = cams
    body = (
      <div className="relative h-full w-full">
        <ParticipantCard trackRef={other} onTogglePin={togglePin(other)} className="h-full w-full" />
        <ParticipantCard
          trackRef={me}
          compact
          className={`absolute right-3 bottom-3 shadow-2xl shadow-black/60 ${
            portrait ? 'aspect-[3/4] w-[30%] max-w-40' : 'aspect-video w-[22%] max-w-72 min-w-36'
          }`}
        />
      </div>
    )
  } else {
    const grid = fitGrid(cams.length, size.width, size.height, GAP, aspect)
    body = (
      <div className="flex h-full w-full flex-wrap content-center items-center justify-center" style={{ gap: GAP }}>
        {grid.w > 0 &&
          cams.map((t) => (
            <ParticipantCard
              key={trackKey(t)}
              trackRef={t}
              onTogglePin={cams.length > 1 ? togglePin(t) : undefined}
              style={{ width: grid.w, height: grid.h }}
            />
          ))}
      </div>
    )
  }

  return (
    <div ref={ref} className="h-full w-full min-h-0 min-w-0">
      {body}
    </div>
  )
}
