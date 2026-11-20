import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CarouselLayout,
  ConnectionStateToast,
  FocusLayout,
  FocusLayoutContainer,
  GridLayout,
  LiveKitRoom,
  MediaDeviceMenu,
  ParticipantTile,
  PreJoin,
  RoomAudioRenderer,
  StartAudio,
  TrackToggle,
  isTrackReference,
  useLocalParticipant,
  useParticipants,
  useRoomContext,
  useRoomInfo,
  useTracks,
  type LocalUserChoices,
} from '@livekit/components-react'
import '@livekit/components-styles'
import { DisconnectReason, RoomEvent, Track } from 'livekit-client'
import { ArrowLeft, ArrowRight, Check, Circle, Link2, Mic, MicOff, PhoneOff, Square, Video } from 'lucide-react'
import {
  endRoom,
  getOpenRoom,
  getRoom,
  getWorkspace,
  joinRoom,
  leaveRoom,
  openRoom,
  startRoomRecording,
  stopRoomRecording,
} from '../api/endpoints'
import type { RecordingState, Room } from '../api/types'
import { Button, ErrorText, Spinner } from '../components/ui'
import { useRoomRecorder } from '../hooks/useRoomRecorder'
import { hasUnsentAudio } from '../lib/roomTrackUploader'
import { errorMessage } from '../lib/utils'
import { useAuth } from '../stores/auth'

/** Địa chỉ LiveKit = chính địa chỉ đang mở web (Vite chuyển tiếp /rtc sang LiveKit) → chỉ cần MỘT địa chỉ. */
const LIVEKIT_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

/** Chia sẻ màn hình chỉ có trên trình duyệt máy tính (điện thoại không có getDisplayMedia). */
const CAN_SHARE_SCREEN = typeof navigator.mediaDevices?.getDisplayMedia === 'function'

type Session = { token: string; choices: LocalUserChoices }

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

/** Khung hình: không ai chia sẻ màn hình → lưới các ô người; có người chia sẻ → màn hình to, người xếp bên cạnh. */
function Stage() {
  const tracks = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true }, // tắt cam vẫn có ô (hiện tên)
      { source: Track.Source.ScreenShare, withPlaceholder: false },
    ],
    { updateOnlyOn: [RoomEvent.ActiveSpeakersChanged], onlySubscribed: false },
  )
  const screen = tracks.filter(isTrackReference).find((t) => t.publication.source === Track.Source.ScreenShare)
  if (!screen) {
    return (
      <GridLayout tracks={tracks} style={{ height: '100%' }}>
        <ParticipantTile />
      </GridLayout>
    )
  }
  return (
    <FocusLayoutContainer style={{ height: '100%' }}>
      <CarouselLayout tracks={tracks.filter((t) => t !== screen)}>
        <ParticipantTile />
      </CarouselLayout>
      <FocusLayout trackRef={screen} />
    </FocusLayoutContainer>
  )
}

function ParticipantList({ hostId, ownerId }: { hostId: number | null; ownerId: number | null }) {
  const participants = useParticipants()
  return (
    <aside className="hidden w-60 shrink-0 overflow-y-auto border-l border-white/10 bg-black/20 p-3 lg:block">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/60">Người tham gia ({participants.length})</h3>
      <ul className="space-y-1.5">
        {participants.map((p) => (
          <li key={p.identity} className="flex items-start gap-2 text-sm text-white/90">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${p.isSpeaking ? 'bg-emerald-400' : 'bg-white/25'}`} />
            <div className="min-w-0 flex-1">
              <div className="truncate">
                {p.name || p.identity}
                {p.isLocal && <span className="text-white/50"> (bạn)</span>}
              </div>
              {/* Hai vai trò được điều khiển phòng (ghi âm, kết thúc): chủ phòng và trưởng nhóm */}
              <div className="mt-0.5 flex flex-wrap gap-1 empty:hidden">
                {Number(p.identity) === hostId && (
                  <span className="rounded bg-brand-500/40 px-1.5 text-[10px]" title="Người đang giữ quyền chủ phòng buổi này">
                    Chủ phòng
                  </span>
                )}
                {Number(p.identity) === ownerId && (
                  <span
                    className="rounded bg-amber-500/40 px-1.5 text-[10px]"
                    title="Trưởng nhóm cũng được bật / dừng ghi và kết thúc phòng"
                  >
                    Trưởng nhóm
                  </span>
                )}
              </div>
            </div>
            <span title={p.isMicrophoneEnabled ? 'Mic đang bật' : 'Mic đang tắt'} className="mt-0.5 shrink-0">
              {p.isMicrophoneEnabled ? (
                <Mic className="size-4 text-emerald-400" aria-label="Mic đang bật" />
              ) : (
                <MicOff className="size-4 text-white/40" aria-label="Mic đang tắt" />
              )}
            </span>
          </li>
        ))}
      </ul>
    </aside>
  )
}

/** Bên trong phòng (đã kết nối LiveKit). */
function LiveRoom({ initial }: { initial: Room }) {
  const code = initial.code
  const qc = useQueryClient()
  const { data: room = initial } = useQuery({ queryKey: ['room-info', code], queryFn: () => getRoom(code), initialData: initial })
  const { metadata } = useRoomInfo()
  const recording = recordingFromMetadata(metadata) ?? room.recording
  const participants = useParticipants()
  const { localParticipant } = useLocalParticipant()
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  // Đường tiếng mic hiện tại của mình. Đổi mic → LiveKit tạo đường tiếng mới, nên kiểm tra lại mỗi giây.
  const [micTrack, setMicTrack] = useState<MediaStreamTrack | undefined>()
  useEffect(() => {
    const read = () => setMicTrack(localParticipant.getTrackPublication(Track.Source.Microphone)?.track?.mediaStreamTrack)
    read()
    const t = window.setInterval(read, 1000)
    return () => window.clearInterval(t)
  }, [localParticipant])

  const recorder = useRoomRecorder(code, recording, micTrack)

  const onDone = (r: Room) => {
    setError('')
    qc.setQueryData(['room-info', code], r)
  }
  const onFail = (e: unknown) => setError(errorMessage(e))
  const start = useMutation({ mutationFn: () => startRoomRecording(code), onSuccess: onDone, onError: onFail })
  const stop = useMutation({ mutationFn: () => stopRoomRecording(code), onSuccess: onDone, onError: onFail })
  const end = useMutation({ mutationFn: () => endRoom(code), onSuccess: (r) => onDone(r.room), onError: onFail })

  // LiveKit báo thông tin phòng đổi (bật / dừng ghi, ĐỔI CHỦ PHÒNG) → hỏi lại backend xem mình có quyền gì
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ['room-info', code] })
  }, [metadata, qc, code])

  // Báo cho mọi người khi quyền chủ phòng đổi chủ
  const [hostNotice, setHostNotice] = useState('')
  const lastHost = useRef(room.host?.id)
  useEffect(() => {
    const id = room.host?.id
    if (id === lastHost.current) return
    lastHost.current = id
    if (!room.host) return
    setHostNotice(room.is_host ? 'Bạn hiện là chủ phòng của buổi họp này.' : `${room.host.full_name} hiện là chủ phòng.`)
    const t = window.setTimeout(() => setHostNotice(''), 8000)
    return () => window.clearTimeout(t)
  }, [room.host, room.is_host])

  // Rời phòng. Chủ phòng rời thì phải chọn: chỉ mình rời (nhượng quyền) hay kết thúc cho mọi người.
  const lkRoom = useRoomContext()
  const [leaveDialog, setLeaveDialog] = useState(false)
  const others = participants.filter((p) => !p.isLocal)
  const nextHost = [...others].sort((a, b) => (a.joinedAt?.getTime() ?? 0) - (b.joinedAt?.getTime() ?? 0))[0]
  const leaveOnly = useMutation({
    mutationFn: () => leaveRoom(code),
    // Báo backend xong (hoặc lỗi mạng) thì vẫn rời: nếu backend chưa biết, sau 1 phút vắng nó tự nhượng quyền
    onSettled: () => void lkRoom.disconnect(),
  })
  const onLeaveClick = () => {
    if (room.is_host) setLeaveDialog(true)
    else void lkRoom.disconnect()
  }

  const link = `${window.location.origin}/room/${code}`

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Thanh trên: tên phòng, trạng thái ghi âm, nút của chủ phòng */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-white/10 px-4 py-2 text-white">
        <h1 className="max-w-full truncate text-sm font-semibold">{room.title}</h1>
        <span className="whitespace-nowrap text-xs text-white/60">
          {room.workspace_name} · {participants.length}/6 người
        </span>
        {recording === 'on' && (
          <span className="flex items-center gap-1.5 rounded-full bg-rose-600 px-2.5 py-0.5 text-xs font-medium">
            <span className="h-2 w-2 animate-pulse rounded-full glass" /> Đang ghi âm
          </span>
        )}
        {recording === 'stopped' && <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs">Đã dừng ghi âm</span>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 px-2.5 py-1 text-xs transition hover:bg-white/10"
            onClick={async () => {
              await navigator.clipboard.writeText(link)
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}
            title={link}
          >
            {copied ? (
              <>
                <Check className="size-3.5 text-emerald-400" aria-hidden="true" /> Đã chép link
              </>
            ) : (
              <>
                <Link2 className="size-3.5" aria-hidden="true" /> Chép link mời
              </>
            )}
          </button>
          {room.can_control && recording === 'idle' && (
            <Button variant="danger" className="!py-1 text-xs" disabled={start.isPending} onClick={() => start.mutate()}>
              <Circle className="fill-current" aria-hidden="true" /> Bắt đầu ghi
            </Button>
          )}
          {room.can_control && recording === 'on' && (
            <Button
              variant="secondary"
              className="!py-1 text-xs"
              disabled={stop.isPending}
              onClick={() => confirm('Dừng ghi âm? Buổi họp này sẽ KHÔNG ghi lại được nữa.') && stop.mutate()}
            >
              <Square className="fill-current" aria-hidden="true" /> Dừng ghi
            </Button>
          )}
          {room.can_control && (
            <Button
              variant="danger"
              className="!py-1 text-xs"
              disabled={end.isPending}
              onClick={() =>
                confirm(
                  recording === 'idle'
                    ? 'Kết thúc buổi họp cho mọi người? (Buổi này không ghi âm nên sẽ không có biên bản.)'
                    : 'Kết thúc buổi họp cho mọi người? Ghi âm sẽ được chuyển thành bản ghi.',
                ) && end.mutate()
              }
            >
              Kết thúc cho mọi người
            </Button>
          )}
        </div>
      </div>

      {recording === 'on' && (
        <p className="bg-rose-950/60 px-4 py-1.5 text-center text-xs text-rose-100">
          Buổi họp đang được ghi âm để làm biên bản. Lời nói của bạn được ghi lại khi mic bật; tắt mic thì không ghi.
          {recorder === 'error' && <b> Không ghi được mic của bạn — hãy kiểm tra kết nối mạng hoặc dùng Chrome / Edge bản mới.</b>}
        </p>
      )}
      {hostNotice && <p className="bg-brand-900/70 px-4 py-1.5 text-center text-xs text-brand-100">{hostNotice}</p>}
      {error && <p className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-900">{error}</p>}

      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1 p-2">
          <Stage />
        </div>
        <ParticipantList hostId={room.host?.id ?? null} ownerId={room.owner_id} />
      </div>

      {/* Thanh điều khiển: mic, cam, chia sẻ màn hình, rời phòng */}
      {/* Điện thoại: chỉ hiện biểu tượng (chữ ẩn dưới 640px) để cả hàng nút vừa màn hình */}
      <div className="lk-control-bar mf-control-bar">
        <div className="lk-button-group">
          <TrackToggle source={Track.Source.Microphone} title="Bật / tắt mic">
            <span className="hidden sm:inline">Mic</span>
          </TrackToggle>
          <div className="lk-button-group-menu">
            <MediaDeviceMenu kind="audioinput" />
          </div>
        </div>
        <div className="lk-button-group">
          <TrackToggle source={Track.Source.Camera} title="Bật / tắt camera">
            <span className="hidden sm:inline">Camera</span>
          </TrackToggle>
          <div className="lk-button-group-menu">
            <MediaDeviceMenu kind="videoinput" />
          </div>
        </div>
        {/* Trình duyệt trên điện thoại không hỗ trợ chia sẻ màn hình → ẩn nút */}
        {CAN_SHARE_SCREEN && (
          <TrackToggle
            source={Track.Source.ScreenShare}
            captureOptions={{ audio: false, selfBrowserSurface: 'include' }}
            title="Chia sẻ màn hình"
          >
            <span className="hidden sm:inline">Chia sẻ màn hình</span>
          </TrackToggle>
        )}
        <button type="button" className="lk-button lk-disconnect-button" onClick={onLeaveClick}>
          <PhoneOff className="size-4" aria-hidden="true" />
          Rời phòng
        </button>
        <StartAudio label="Bấm để nghe mọi người" />
      </div>

      {/* Chủ phòng bấm "Rời phòng": hỏi lại như Google Meet để không vô tình bỏ phòng treo */}
      {leaveDialog && (
        <div className="fixed inset-0 z-50 flex animate-fade items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setLeaveDialog(false)}>
          <div className="glass-blur w-full max-w-sm animate-pop rounded-2xl border p-5 text-slate-800" onClick={(e) => e.stopPropagation()}>
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
    </div>
  )
}

/** Sau khi phòng kết thúc: chờ gửi nốt ghi âm của mình, rồi dẫn tới cuộc họp (nếu buổi họp có ghi âm). */
function EndedView({ code, kicked }: { code: string; kicked: boolean }) {
  const [unsent, setUnsent] = useState(hasUnsentAudio())
  useEffect(() => {
    const t = window.setInterval(() => setUnsent(hasUnsentAudio()), 500)
    return () => window.clearInterval(t)
  }, [])
  const { data: room } = useQuery({
    queryKey: ['room-info', code],
    queryFn: () => getRoom(code),
    // Phòng vừa đóng: hỏi lại vài giây một lần tới khi biết buổi họp có sinh ra cuộc họp không
    refetchInterval: (q) => (q.state.data?.status === 'ended' ? false : 2000),
  })
  const recorded = room ? room.recording !== 'idle' : false

  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <div className="glass mx-auto flex size-16 items-center justify-center rounded-2xl border">
        <Video className="size-8 text-brand-600" aria-hidden="true" />
      </div>
      <h1 className="mt-3 text-xl font-bold">{kicked || room?.status === 'ended' ? 'Buổi họp đã kết thúc' : 'Bạn đã rời phòng'}</h1>
      {room && <p className="mt-1 text-sm text-slate-500">{room.title}</p>}

      {unsent && (
        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Đang gửi nốt ghi âm của bạn lên máy chủ… <b>đừng đóng tab này.</b>
        </p>
      )}
      {room?.status === 'ended' && !recorded && (
        <p className="mt-4 text-sm text-slate-600">Buổi họp này không ghi âm nên không có bản ghi và biên bản.</p>
      )}
      {room?.status === 'ended' && recorded && (
        <p className="mt-4 text-sm text-slate-600">
          Ghi âm của mọi người đang được chuyển thành bản ghi có tên người nói. Sau đó chủ phòng bấm tóm tắt để AI tách đầu việc.
        </p>
      )}

      <div className="mt-6 flex flex-col items-center gap-2">
        {room?.meeting_id && (
          <Link to={`/meetings/${room.meeting_id}`}>
            <Button>
              Xem cuộc họp & bản ghi <ArrowRight aria-hidden="true" />
            </Button>
          </Link>
        )}
        {room?.status === 'open' && (
          <a href={`/room/${code}`}>
            <Button variant="secondary">Vào lại phòng</Button>
          </a>
        )}
        {room && (
          <Link to={`/workspaces/${room.workspace_id}`} className="text-sm text-brand-600 hover:underline">
            Về trang nhóm
          </Link>
        )}
      </div>
    </div>
  )
}

/** Màn hình chờ dùng chung: xem trước, chọn mic / cam rồi bấm "Vào phòng". */
function Lobby({
  backTo,
  backLabel,
  title,
  subtitle,
  notices,
  pending,
  error,
  onDeviceError,
  onSubmit,
}: {
  backTo: string
  backLabel: string
  title: string
  subtitle: ReactNode
  notices?: ReactNode
  pending: boolean
  error: string
  onDeviceError: (message: string) => void
  onSubmit: (choices: LocalUserChoices) => void
}) {
  const me = useAuth((s) => s.user)!
  return (
    <div className="mx-auto w-full max-w-xl px-4 py-8">
      <Link to={backTo} className="text-sm text-slate-500 hover:underline">
        <ArrowLeft className="mr-1 inline size-4 align-[-3px]" aria-hidden="true" />
        {backLabel}
      </Link>
      <h1 className="mt-2 flex items-center gap-2.5 text-2xl font-bold tracking-tight">
        <Video className="size-7 shrink-0 text-brand-600" aria-hidden="true" />
        {title}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {subtitle} · bạn vào với tên <b>{me.full_name}</b>
      </p>
      {notices}
      <div data-lk-theme="default" className="mf-prejoin mt-4 overflow-hidden rounded-2xl shadow-xl ring-1 ring-black/5">
        <PreJoin
          defaults={{ username: me.full_name, audioEnabled: true, videoEnabled: false }}
          persistUserChoices={false}
          joinLabel={pending ? 'Đang vào…' : 'Vào phòng'}
          micLabel="Micro"
          camLabel="Camera"
          userLabel="Tên"
          onValidate={() => !pending}
          onSubmit={onSubmit}
          onError={(e) => onDeviceError(`Không mở được mic / camera: ${e.message}. Bạn vẫn vào phòng được, rồi bật lại sau.`)}
        />
      </div>
      <div className="mt-2">
        <ErrorText>{error}</ErrorText>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Mic bật sẵn, camera tắt sẵn — đổi ngay ở trên nếu muốn. Nên đeo tai nghe để mic không thu lại tiếng người khác.
      </p>
    </div>
  )
}

/**
 * Màn hình chờ của phòng CHƯA TỒN TẠI (/room/new?ws=<id nhóm>).
 *
 * Bấm "📹 Online Meeting" trên trang nhóm chỉ đưa tới đây — CHƯA tạo phòng. Phòng chỉ được tạo khi
 * bấm "Vào phòng". Nhờ vậy bấm nhầm rồi quay lại không để lại "phòng ma" làm người khác thấy nút
 * "Tham gia phòng" trong khi chẳng có ai họp.
 */
function NewRoomLobby() {
  const [params] = useSearchParams()
  const workspaceId = Number(params.get('ws'))
  const navigate = useNavigate()
  const qc = useQueryClient()
  const valid = Number.isInteger(workspaceId) && workspaceId > 0
  const { data: ws, error } = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => getWorkspace(workspaceId),
    enabled: valid,
    retry: false,
  })
  const { data: existing, isFetchedAfterMount: checked } = useQuery({
    queryKey: ['room', workspaceId],
    queryFn: () => getOpenRoom(workspaceId),
    enabled: valid,
  })
  const [message, setMessage] = useState('')

  const create = useMutation({
    // Lúc này mới tạo phòng (người bấm là chủ phòng) rồi lấy vé vào luôn
    mutationFn: async (choices: LocalUserChoices) => {
      const room = await openRoom(workspaceId)
      const res = await joinRoom(room.code)
      return { res, choices }
    },
    onSuccess: ({ res, choices }) => {
      qc.setQueryData(['room-info', res.room.code], res.room)
      // Sang đúng địa chỉ của phòng, mang theo vé để vào thẳng (không phải qua màn hình chờ lần nữa)
      navigate(`/room/${res.room.code}`, { replace: true, state: { session: { token: res.token, choices } satisfies Session } })
      qc.invalidateQueries({ queryKey: ['room', workspaceId] })
    },
    onError: (e) => setMessage(errorMessage(e)),
  })

  // Trong lúc mình còn ở màn hình chờ, người khác đã mở phòng → chuyển sang phòng đó (mỗi nhóm một phòng)
  const busy = create.isPending || create.isSuccess
  // (`checked`: chỉ tin kết quả vừa hỏi lại máy chủ, không tin bản lưu tạm có thể là phòng đã kết thúc)
  useEffect(() => {
    if (existing && checked && !busy) navigate(`/room/${existing.code}`, { replace: true })
  }, [existing, checked, busy, navigate])

  if (!valid || error) {
    return (
      <div className="mx-auto max-w-md px-4 py-16 text-center">
        <p className="text-rose-600">{errorMessage(error, 'Không tìm thấy nhóm để mở phòng họp')}</p>
        <Link to="/" className="mt-4 inline-block text-sm text-brand-600 hover:underline">
          Về trang nhóm
        </Link>
      </div>
    )
  }
  if (!ws) return <Spinner text="Đang chuẩn bị phòng họp…" />

  return (
    <Lobby
      backTo={`/workspaces/${workspaceId}`}
      backLabel="Về trang nhóm"
      title="Online Meeting mới"
      subtitle={
        <>
          Nhóm <b>{ws.name}</b> · bạn sẽ là chủ phòng
        </>
      }
      notices={
        <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-600">
          Phòng chỉ được mở khi bạn bấm <b>“Vào phòng”</b>. Quay lại lúc này thì không có phòng nào được tạo.
        </p>
      }
      pending={busy}
      error={message}
      onDeviceError={setMessage}
      onSubmit={(choices) => create.mutate(choices)}
    />
  )
}

/** Phòng đã tồn tại: màn hình chờ → trong phòng → sau khi rời / kết thúc. */
function ExistingRoom({ code }: { code: string }) {
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const { data: room, isLoading, error } = useQuery({ queryKey: ['room-info', code], queryFn: () => getRoom(code), retry: false })
  // Vừa mở phòng mới xong thì đã có sẵn vé (NewRoomLobby gửi kèm) → vào thẳng
  const handedOver = (location.state as { session?: Session } | null)?.session ?? null
  const [session, setSession] = useState<Session | null>(handedOver)
  const [after, setAfter] = useState<null | 'ended' | 'left' | 'lost'>(null)
  const [joinError, setJoinError] = useState('')

  // Vé chỉ dùng một lần: xóa khỏi lịch sử trình duyệt để tải lại trang không tự vào phòng bằng vé cũ
  useEffect(() => {
    if (handedOver) navigate(location.pathname, { replace: true, state: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const join = useMutation({
    mutationFn: (choices: LocalUserChoices) => joinRoom(code).then((res) => ({ res, choices })),
    onSuccess: ({ res, choices }) => {
      setJoinError('')
      qc.setQueryData(['room-info', code], res.room)
      if (res.joined_workspace) qc.invalidateQueries({ queryKey: ['workspaces'] })
      setAfter(null)
      setSession({ token: res.token, choices })
    },
    onError: (e) => {
      setJoinError(errorMessage(e))
      qc.invalidateQueries({ queryKey: ['room-info', code] })
    },
  })

  // Cảnh báo khi đóng tab lúc đang trong phòng hoặc còn ghi âm chưa gửi xong
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (session || hasUnsentAudio()) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [session])

  const lkOptions = useMemo(
    () => ({
      adaptiveStream: true, // chỉ nhận hình ở độ phân giải vừa với ô đang hiện → nhẹ máy
      dynacast: true, // không ai xem thì ngừng gửi hình
      audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    }),
    [],
  )

  if (isLoading) return <Spinner text="Đang mở phòng họp…" />
  if (error || !room) {
    return (
      <div className="mx-auto max-w-md px-4 py-16 text-center">
        <p className="text-rose-600">{errorMessage(error, 'Link phòng họp không đúng')}</p>
        <Link to="/" className="mt-4 inline-block text-sm text-brand-600 hover:underline">
          Về trang nhóm
        </Link>
      </div>
    )
  }

  // Đang trong phòng
  if (session && room.status === 'open') {
    return (
      <LiveKitRoom
        data-lk-theme="default"
        className="flex min-h-0 w-full flex-1 flex-col overflow-hidden"
        // dvh = chiều cao THẬT đang nhìn thấy (trên điện thoại, 100vh tính cả phần bị thanh địa chỉ che
        // → thanh nút ở đáy bị khuất). 3.5rem là thanh tiêu đề MeetFlow phía trên.
        style={{ height: 'calc(100dvh - 3.5rem)' }}
        serverUrl={LIVEKIT_URL}
        token={session.token}
        connect
        audio={session.choices.audioEnabled ? { deviceId: session.choices.audioDeviceId || undefined } : false}
        video={session.choices.videoEnabled ? { deviceId: session.choices.videoDeviceId || undefined } : false}
        options={lkOptions}
        onDisconnected={(reason) => {
          setSession(null)
          qc.invalidateQueries({ queryKey: ['room-info', code] })
          qc.invalidateQueries({ queryKey: ['room', room.workspace_id] })
          if (reason === DisconnectReason.CLIENT_INITIATED) {
            if (hasUnsentAudio()) setAfter('left')
            else navigate(`/workspaces/${room.workspace_id}`)
          } else if (reason === DisconnectReason.ROOM_DELETED) setAfter('ended')
          else setAfter('lost')
        }}
        onError={(e) => setJoinError(e.message)}
      >
        <LiveRoom initial={room} />
      </LiveKitRoom>
    )
  }

  if (room.status === 'ended' || after === 'ended' || after === 'left') {
    return <EndedView code={code} kicked={after === 'ended'} />
  }

  // Màn hình chờ
  return (
    <Lobby
      backTo={room.is_member ? `/workspaces/${room.workspace_id}` : '/'}
      backLabel={room.is_member ? 'Về trang nhóm' : 'Trang chủ'}
      title={room.title}
      subtitle={
        <>
          Nhóm <b>{room.workspace_name}</b>
          {room.host && <> · chủ phòng {room.host.full_name}</>}
        </>
      }
      notices={
        <>
          {!room.is_member && (
            <p className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
              Bạn chưa ở trong nhóm <b>{room.workspace_name}</b>. Bấm “Vào phòng” là bạn được thêm vào nhóm để nhận việc sau buổi
              họp.
            </p>
          )}
          {room.recording === 'on' && (
            <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
              <span className="mr-1.5 inline-block size-2 animate-pulse rounded-full bg-rose-600 align-middle" aria-hidden="true" />
              <b>Phòng đang được ghi âm</b> để làm biên bản. Lời nói của bạn sẽ được ghi lại khi mic bật.
            </p>
          )}
          {after === 'lost' && (
            <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Bạn bị mất kết nối với phòng họp. Phần ghi âm đã có vẫn được giữ; bấm “Vào phòng” để vào lại.
            </p>
          )}
        </>
      }
      pending={join.isPending}
      error={joinError}
      onDeviceError={setJoinError}
      onSubmit={(choices) => join.mutate(choices)}
    />
  )
}

/**
 * Trang phòng họp trực tuyến.
 *
 *   /room/new?ws=<nhóm>  bấm "📹 Online Meeting": màn hình chờ, CHƯA có phòng. Bấm "Vào phòng" mới tạo phòng.
 *   /room/<mã>           phòng đã có (bấm "Tham gia phòng" hoặc mở link mời):
 *        (chưa đăng nhập → đăng nhập / đăng ký rồi quay lại) → màn hình chờ → "Vào phòng": backend cấp VÉ
 *        (người chưa ở trong nhóm được tự thêm vào nhóm) → kết nối LiveKit
 */
export default function RoomPage() {
  const { code = '' } = useParams()
  return code === 'new' ? <NewRoomLobby /> : <ExistingRoom key={code} code={code} />
}
