import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ConnectionStateToast,
  RoomAudioRenderer,
  StartAudio,
  useLocalParticipant,
  useParticipantAttribute,
  useParticipants,
  useRoomContext,
  useRoomInfo,
} from '@livekit/components-react'
import { RoomEvent, Track } from 'livekit-client'
import { Hand } from 'lucide-react'
import { endRoom, getRoom, leaveRoom, startRoomRecording, stopRoomRecording } from '../../api/endpoints'
import type { RecordingState, Room } from '../../api/types'
import { useRoomRecorder } from '../../hooks/useRoomRecorder'
import { errorMessage } from '../../lib/utils'
import { Button } from '../ui'
import MeetingStage from './MeetingStage'
import MiniCall from './MiniCall'
import { DesktopControls, MobileControls, type ControlActions } from './RoomControls'
import { InfoPanel, PanelShell, PeoplePanel, type PanelKind } from './RoomPanels'
import { useIsNarrow } from './layout'

/** full: phủ cả màn hình (đang ở trang phòng họp) · mini: ô nhỏ nổi ở góc (đang xem trang khác) */
export type CallMode = 'full' | 'mini'

/** Trạng thái ghi âm của phòng mà LiveKit vừa báo (chủ phòng bật / dừng ghi → mọi người biết ngay). */
function recordingFromMetadata(metadata: string | undefined): RecordingState | null {
  if (!metadata) return null
  try {
    const r = (JSON.parse(metadata) as { recording?: RecordingState }).recording
    return r === 'idle' || r === 'on' || r === 'stopped' ? r : null
  } catch {
    return null
  }
}

/** Thông báo nhỏ nổi ở giữa phía trên (giơ tay, đổi chủ phòng, lỗi…), tự tắt sau vài giây. */
type Toast = { id: number; text: string; tone: 'info' | 'warn' | 'hand' }

/**
 * Bên trong phòng (đã kết nối LiveKit) — bố trí kiểu Google Meet, luôn nền tối.
 *
 * Thành phần này sống suốt cuộc họp, kể cả khi thu nhỏ: máy ghi âm, thông báo, giơ tay, hộp thoại rời
 * phòng… vẫn chạy; chỉ phần HIỂN THỊ đổi giữa toàn màn hình và ô nhỏ (`mode`).
 */
export default function LiveRoom({ initial, mode }: { initial: Room; mode: CallMode }) {
  const code = initial.code
  const qc = useQueryClient()
  const { data: room = initial } = useQuery({ queryKey: ['room-info', code], queryFn: () => getRoom(code), initialData: initial })
  const { metadata } = useRoomInfo()
  const recording = recordingFromMetadata(metadata) ?? room.recording
  const participants = useParticipants()
  const { localParticipant, isScreenShareEnabled } = useLocalParticipant()
  const lkRoom = useRoomContext()
  const narrow = useIsNarrow()
  const [panel, setPanel] = useState<PanelKind | null>(null)
  const [pinned, setPinned] = useState<string | null>(null)

  // ---- Thông báo nổi ----
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)
  const pushToast = useCallback((text: string, tone: Toast['tone'] = 'info', ms = 6000) => {
    const id = ++toastId.current
    setToasts((t) => [...t.slice(-2), { id, text, tone }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ms)
  }, [])

  // Đường tiếng mic hiện tại của mình. Đổi mic → LiveKit tạo đường tiếng mới, nên kiểm tra lại mỗi giây.
  const [micTrack, setMicTrack] = useState<MediaStreamTrack | undefined>()
  useEffect(() => {
    const read = () => setMicTrack(localParticipant.getTrackPublication(Track.Source.Microphone)?.track?.mediaStreamTrack)
    read()
    const t = window.setInterval(read, 1000)
    return () => window.clearInterval(t)
  }, [localParticipant])

  const recorder = useRoomRecorder(code, recording, micTrack)

  const onDone = (r: Room) => qc.setQueryData(['room-info', code], r)
  const onFail = (e: unknown) => pushToast(errorMessage(e), 'warn', 8000)
  const start = useMutation({ mutationFn: () => startRoomRecording(code), onSuccess: onDone, onError: onFail })
  const stop = useMutation({ mutationFn: () => stopRoomRecording(code), onSuccess: onDone, onError: onFail })
  const end = useMutation({ mutationFn: () => endRoom(code), onSuccess: (r) => onDone(r.room), onError: onFail })

  // LiveKit báo thông tin phòng đổi (bật / dừng ghi, ĐỔI CHỦ PHÒNG) → hỏi lại backend xem mình có quyền gì
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ['room-info', code] })
  }, [metadata, qc, code])

  // Báo cho mọi người khi quyền chủ phòng đổi chủ
  const lastHost = useRef(room.host?.id)
  useEffect(() => {
    const id = room.host?.id
    if (id === lastHost.current) return
    lastHost.current = id
    if (room.host) pushToast(room.is_host ? 'Bạn hiện là chủ phòng của buổi họp này.' : `${room.host.full_name} hiện là chủ phòng.`)
  }, [room.host, room.is_host, pushToast])

  // ---- Giơ tay: thuộc tính `hand` (= thời điểm giơ) của chính mình, mọi người đều thấy ----
  const myHand = useParticipantAttribute('hand', { participant: localParticipant })
  const toggleHand = () => {
    localParticipant
      .setAttributes({ hand: myHand ? '' : String(Date.now()) })
      .catch((e: unknown) => pushToast(`Không giơ tay được: ${errorMessage(e)}`, 'warn'))
  }
  useEffect(() => {
    const onAttrs = (changed: Record<string, string>, p: { isLocal: boolean; name?: string; identity: string }) => {
      if (!p.isLocal && changed.hand) pushToast(`${p.name || p.identity} đang giơ tay`, 'hand')
    }
    lkRoom.on(RoomEvent.ParticipantAttributesChanged, onAttrs)
    return () => {
      lkRoom.off(RoomEvent.ParticipantAttributesChanged, onAttrs)
    }
  }, [lkRoom, pushToast])
  const raisedCount = participants.filter((p) => p.attributes?.hand).length

  // Ghim người đã rời phòng → bỏ ghim
  useEffect(() => {
    if (pinned && !participants.some((p) => pinned.startsWith(`${p.identity}:`))) setPinned(null)
  }, [participants, pinned])

  // ---- Ghi âm / kết thúc ----
  const startRecording = () => start.mutate()
  const stopRecording = () => confirm('Dừng ghi âm? Buổi họp này sẽ KHÔNG ghi lại được nữa.') && stop.mutate()
  const endForAll = () =>
    confirm(
      recording === 'idle'
        ? 'Kết thúc buổi họp cho mọi người? (Buổi này không ghi âm nên sẽ không có biên bản.)'
        : 'Kết thúc buổi họp cho mọi người? Ghi âm sẽ được chuyển thành bản ghi.',
    ) && end.mutate()

  // Rời phòng. Chủ phòng rời thì phải chọn: chỉ mình rời (nhượng quyền) hay kết thúc cho mọi người.
  const [leaveDialog, setLeaveDialog] = useState(false)
  const others = participants.filter((p) => !p.isLocal)
  const nextHost = [...others].sort((a, b) => (a.joinedAt?.getTime() ?? 0) - (b.joinedAt?.getTime() ?? 0))[0]
  const leaveOnly = useMutation({
    mutationFn: () => leaveRoom(code),
    // Báo backend xong (hoặc lỗi mạng) thì vẫn rời: nếu backend chưa biết, sau 1 phút vắng nó tự nhượng quyền
    onSettled: () => void lkRoom.disconnect(),
  })
  const onLeave = () => {
    if (room.is_host) setLeaveDialog(true)
    else void lkRoom.disconnect()
  }

  const controls: ControlActions = {
    room,
    recording,
    handRaised: Boolean(myHand),
    onToggleHand: toggleHand,
    onStartRecording: startRecording,
    onStopRecording: stopRecording,
    onEndForAll: endForAll,
    onLeave,
    busy: start.isPending || stop.isPending || end.isPending,
    panel,
    onPanel: setPanel,
    participantCount: participants.length,
    raisedCount,
  }

  return (
    // Thứ tự các phần tử con giữ cố định giữa hai chế độ → đổi toàn màn hình ↔ ô nhỏ chỉ thay phần đầu,
    // phần phát tiếng (RoomAudioRenderer) không bị dựng lại nên tiếng không bị ngắt.
    <>
      {mode === 'full' ? (
        <div className="flex h-full min-h-0 flex-col">
          {/* Phía trên: trạng thái ghi âm (+ tên phòng trên điện thoại) */}
          <div className="flex shrink-0 items-center gap-2 px-3 pt-3 pb-1 text-white sm:px-4">
            {recording === 'on' && (
              <span
                className="flex items-center gap-1.5 rounded-full bg-rose-500/90 px-2.5 py-1 text-xs font-medium"
                title="Lời nói được ghi lại khi mic bật; tắt mic thì không ghi"
              >
                <span className="size-2 animate-pulse rounded-full bg-white" aria-hidden="true" /> Đang ghi âm
              </span>
            )}
            {recording === 'stopped' && <span className="rounded-full bg-white/15 px-2.5 py-1 text-xs">Đã dừng ghi âm</span>}
            {narrow && <span className="min-w-0 truncate text-sm font-medium text-white/90">{room.title}</span>}
            {recorder === 'error' && recording === 'on' && (
              <span className="ml-auto rounded-full bg-amber-400 px-2.5 py-1 text-xs font-medium text-black">
                Không ghi được mic của bạn — kiểm tra mạng hoặc dùng Chrome / Edge mới
              </span>
            )}
          </div>

          {/* Đang chia sẻ màn hình (như Meet: nhắc + nút dừng) */}
          {isScreenShareEnabled && (
            <div className="mx-auto mb-1 flex items-center gap-3 rounded-full bg-brand-500 px-4 py-1.5 text-sm text-white shadow-lg">
              Bạn đang chia sẻ màn hình
              <button
                type="button"
                className="rounded-full bg-white/20 px-3 py-0.5 text-xs font-medium transition hover:bg-white/30"
                onClick={() => void localParticipant.setScreenShareEnabled(false)}
              >
                Dừng chia sẻ
              </button>
            </div>
          )}

          <div className="flex min-h-0 flex-1">
            <div className="min-h-0 min-w-0 flex-1 px-2 pb-2 sm:px-3">
              <MeetingStage pinned={pinned} onPin={setPinned} narrow={narrow} />
            </div>
            {panel && (
              <PanelShell
                title={panel === 'people' ? `Người tham gia (${participants.length})` : 'Thông tin buổi họp'}
                narrow={narrow}
                onClose={() => setPanel(null)}
              >
                {panel === 'people' ? (
                  <PeoplePanel room={room} pinned={pinned} onPin={setPinned} />
                ) : (
                  <InfoPanel room={room} recording={recording} />
                )}
              </PanelShell>
            )}
          </div>

          {narrow ? <MobileControls {...controls} /> : <DesktopControls {...controls} />}
        </div>
      ) : (
        <MiniCall room={room} recording={recording} recorderError={recorder === 'error' && recording === 'on'} narrow={narrow} onLeave={onLeave} />
      )}

      {/* Thông báo nổi (cả khi thu nhỏ: ai giơ tay, đổi chủ phòng… vẫn báo) */}
      <div className={`pointer-events-none fixed inset-x-0 z-30 flex flex-col items-center gap-2 px-4 ${mode === 'full' ? 'top-14' : 'top-16'}`}>
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`flex animate-pop items-center gap-2 rounded-full px-4 py-2 text-sm shadow-xl ${
              t.tone === 'warn' ? 'bg-amber-400 text-black' : 'bg-[var(--room-panel)] text-white'
            }`}
          >
            {t.tone === 'hand' && <Hand className="size-4 text-amber-400" aria-hidden="true" />}
            {t.text}
          </div>
        ))}
      </div>
      <div className="fixed top-3 left-1/2 z-[61] -translate-x-1/2">
        <StartAudio label="Bấm để nghe mọi người" />
      </div>

      {/* Chủ phòng bấm "Rời phòng": hỏi lại như Google Meet để không vô tình bỏ phòng treo */}
      {leaveDialog && (
        <div className="fixed inset-0 z-[61] flex animate-fade items-center justify-center bg-black/60 p-4" onClick={() => setLeaveDialog(false)}>
          <div className="w-full max-w-sm animate-pop rounded-2xl bg-[var(--room-panel)] p-5 text-slate-800 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-base font-semibold">Bạn là chủ phòng</h2>
            {others.length > 0 ? (
              <p className="mt-1 text-sm text-slate-600">
                Trong phòng còn {others.length} người. Bạn muốn chỉ mình rời đi, hay kết thúc buổi họp cho tất cả?
              </p>
            ) : (
              <p className="mt-1 text-sm text-slate-600">
                Bạn là người cuối cùng trong phòng. Rời phòng sẽ <b>kết thúc buổi họp</b>
                {recording !== 'idle' && ' và ghi âm sẽ được chuyển thành bản ghi'}.
              </p>
            )}
            <div className="mt-4 flex flex-col gap-2">
              {others.length > 0 && (
                <Button variant="secondary" disabled={leaveOnly.isPending || end.isPending} onClick={() => leaveOnly.mutate()}>
                  Chỉ mình tôi rời
                  {nextHost && <span className="font-normal text-slate-500"> — {nextHost.name || 'người kế tiếp'} thành chủ phòng</span>}
                </Button>
              )}
              <Button
                variant="danger"
                disabled={leaveOnly.isPending || end.isPending}
                onClick={() => end.mutate(undefined, { onSettled: () => setLeaveDialog(false) })}
              >
                {others.length > 0 ? 'Kết thúc cho mọi người' : 'Rời phòng và kết thúc buổi họp'}
              </Button>
              <Button variant="ghost" onClick={() => setLeaveDialog(false)}>
                Ở lại
              </Button>
            </div>
          </div>
        </div>
      )}

      <RoomAudioRenderer />
      <ConnectionStateToast />
    </>
  )
}
