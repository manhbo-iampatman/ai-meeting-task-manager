import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams, type NavigateFunction } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PreJoin, type LocalUserChoices } from '@livekit/components-react'
import '@livekit/components-styles'
import { ArrowLeft, ArrowRight, Video } from 'lucide-react'
import { getOpenRoom, getRoom, getWorkspace, joinRoom, openRoom } from '../api/endpoints'
import { Button, ErrorText, Spinner } from '../components/ui'
import { hasUnsentAudio } from '../lib/roomTrackUploader'
import { errorMessage } from '../lib/utils'
import { useAuth } from '../stores/auth'
import { useCall, type CallSession } from '../stores/call'

/**
 * Vào cuộc họp (phương án B): giao vé cho `CallHost` (cuộc họp sống ở cấp ứng dụng) và đặt lịch sử trình
 * duyệt sao cho nút / cử chỉ Quay lại đưa về TRANG NHÓM → cuộc họp thu nhỏ, không thoát khỏi MeetFlow.
 *
 * Trang phòng là trang ĐẦU TIÊN mở trong tab (bấm link mời từ Zalo, mở sau khi đăng nhập…) thì phía sau
 * không có trang MeetFlow nào → chèn trang nhóm vào phía sau rồi mới tới phòng.
 */
function enterCall(navigate: NavigateFunction, session: CallSession) {
  useCall.getState().start(session)
  const roomUrl = `/room/${session.code}`
  // React Router đánh số các trang đã mở trong tab này: idx 0 = trang đầu tiên
  const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
  if (idx === 0) {
    navigate(`/workspaces/${session.room.workspace_id}`, { replace: true })
    navigate(roomUrl)
  } else if (window.location.pathname !== roomUrl) {
    navigate(roomUrl, { replace: true }) // /room/new → địa chỉ thật của phòng (thay chỗ, không thêm bước)
  }
}

/** Đang họp ở phòng khác → chưa cho vào phòng này (mỗi lúc chỉ họp một phòng). */
function OtherCallNotice({ other }: { other: CallSession }) {
  return (
    <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
      Bạn đang ở trong cuộc họp <b>{other.room.title}</b> (nhóm {other.room.workspace_name}). Mỗi lúc chỉ họp được một
      phòng — rời cuộc họp đó (ô nhỏ ở góc màn hình) rồi mới vào phòng này.
    </p>
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
  blocked = false,
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
  /** chưa được vào (đang họp ở phòng khác) → khóa nút "Vào phòng" */
  blocked?: boolean
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
          onValidate={() => !pending && !blocked}
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
  const active = useCall((s) => s.session)

  const create = useMutation({
    // Lúc này mới tạo phòng (người bấm là chủ phòng) rồi lấy vé vào luôn
    mutationFn: async (choices: LocalUserChoices) => {
      const room = await openRoom(workspaceId)
      const res = await joinRoom(room.code)
      return { res, choices }
    },
    onSuccess: ({ res, choices }) => {
      qc.setQueryData(['room-info', res.room.code], res.room)
      qc.invalidateQueries({ queryKey: ['room', workspaceId] })
      // Vào thẳng phòng vừa mở (không phải qua màn hình chờ lần nữa), địa chỉ đổi sang /room/<mã>
      enterCall(navigate, { code: res.room.code, token: res.token, choices, room: res.room })
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
        <>
          {active && <OtherCallNotice other={active} />}
          <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-600">
            Phòng chỉ được mở khi bạn bấm <b>“Vào phòng”</b>. Quay lại lúc này thì không có phòng nào được tạo.
          </p>
        </>
      }
      pending={busy}
      blocked={Boolean(active)}
      error={message}
      onDeviceError={setMessage}
      onSubmit={(choices) => create.mutate(choices)}
    />
  )
}

/** Phòng đã tồn tại: màn hình chờ → trong phòng (do `CallHost` vẽ) → sau khi rời / kết thúc. */
function ExistingRoom({ code }: { code: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: room, isLoading, error } = useQuery({ queryKey: ['room-info', code], queryFn: () => getRoom(code), retry: false })
  const active = useCall((s) => s.session)
  // Cuộc họp ở phòng này vừa kết thúc / mình rời / rớt mạng (CallHost ghi lại)
  const ended = useCall((s) => (s.ended?.code === code ? s.ended : null))
  const after = ended?.reason ?? null
  const [joinError, setJoinError] = useState('')

  const join = useMutation({
    mutationFn: (choices: LocalUserChoices) => joinRoom(code).then((res) => ({ res, choices })),
    onSuccess: ({ res, choices }) => {
      setJoinError('')
      qc.setQueryData(['room-info', code], res.room)
      if (res.joined_workspace) qc.invalidateQueries({ queryKey: ['workspaces'] })
      enterCall(navigate, { code, token: res.token, choices, room: res.room })
    },
    onError: (e) => {
      setJoinError(errorMessage(e))
      qc.invalidateQueries({ queryKey: ['room-info', code] })
    },
  })

  // Đang họp ở chính phòng này → CallHost đang vẽ cuộc họp toàn màn hình đè lên trang, ở đây không cần gì
  if (active?.code === code) return null

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

  if (room.status === 'ended' || after === 'ended' || after === 'left') {
    return <EndedView code={code} kicked={after === 'ended'} />
  }

  const other = active && active.code !== code ? active : null

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
          {other && <OtherCallNotice other={other} />}
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
      blocked={Boolean(other)}
      error={joinError || ended?.message || ''}
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
