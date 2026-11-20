import { useCallback, useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { LiveKitRoom } from '@livekit/components-react'
import '@livekit/components-styles'
import { ConnectionError, DisconnectReason } from 'livekit-client'
import { hasUnsentAudio } from '../../lib/roomTrackUploader'
import { useCall, type CallSession } from '../../stores/call'
import LiveRoom, { type CallMode } from './LiveRoom'

/** Địa chỉ LiveKit = chính địa chỉ đang mở web (Vite chuyển tiếp /rtc sang LiveKit) → chỉ cần MỘT địa chỉ. */
const LIVEKIT_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

const LK_OPTIONS = {
  adaptiveStream: true, // chỉ nhận hình ở độ phân giải vừa với ô đang hiện → nhẹ máy (thu nhỏ thì nhận hình nhỏ)
  dynacast: true, // không ai xem thì ngừng gửi hình
  audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
}

/**
 * Giữ màn hình luôn sáng trong lúc họp (Wake Lock). Điện thoại thường tự tắt màn hình sau ~30 giây không
 * chạm; màn hình tắt thì trình duyệt ngừng thu mic → mất tiếng trong bản ghi.
 * Trình duyệt tự nhả khóa khi chuyển sang ứng dụng khác → quay lại web thì xin lại.
 * Trình duyệt không hỗ trợ / từ chối (pin yếu…) thì thôi, cuộc họp vẫn chạy bình thường.
 */
function useWakeLock() {
  useEffect(() => {
    if (!('wakeLock' in navigator)) return
    let lock: WakeLockSentinel | null = null
    let asking = false
    let disposed = false
    const acquire = async () => {
      if (disposed || asking || lock || document.visibilityState !== 'visible') return
      asking = true
      try {
        const l = await navigator.wakeLock.request('screen')
        if (disposed) {
          void l.release().catch(() => {})
          return
        }
        lock = l
        l.addEventListener('release', () => {
          if (lock === l) lock = null
        })
      } catch {
        // bị từ chối → bỏ qua
      } finally {
        asking = false
      }
    }
    void acquire()
    const onVisibility = () => void acquire()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      disposed = true
      document.removeEventListener('visibilitychange', onVisibility)
      void lock?.release().catch(() => {})
      lock = null
    }
  }, [])
}

/**
 * Kết nối LiveKit của cuộc họp đang diễn ra — gắn với CẢ ỨNG DỤNG (qua `CallHost`), không gắn với trang
 * phòng họp, nên chuyển trang không làm rớt cuộc họp.
 *
 * Gắn thẳng vào <body> (portal): khung trang có hiệu ứng chuyển cảnh dùng `transform`, mà `position: fixed`
 * bên trong phần tử có transform chỉ phủ được khung đó → không che được thanh MeetFlow.
 */
export default function ActiveCall({ session, mode }: { session: CallSession; mode: CallMode }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { code, room, choices } = session
  useWakeLock()

  const onDisconnected = useCallback(
    (reason?: DisconnectReason) => {
      const { finish } = useCall.getState()
      qc.invalidateQueries({ queryKey: ['room-info', code] })
      qc.invalidateQueries({ queryKey: ['room', room.workspace_id] })
      const onRoomPage = window.location.pathname === `/room/${code}`
      if (reason === DisconnectReason.CLIENT_INITIATED) {
        // Tự bấm rời ở màn hình lớn, không còn ghi âm phải gửi → về trang nhóm như trước
        if (onRoomPage && !hasUnsentAudio()) {
          finish(null)
          navigate(`/workspaces/${room.workspace_id}`)
        } else finish({ code, title: room.title, reason: 'left' })
      } else if (reason === DisconnectReason.ROOM_DELETED) finish({ code, title: room.title, reason: 'ended' })
      else finish({ code, title: room.title, reason: 'lost' })
    },
    [qc, code, room.workspace_id, room.title, navigate],
  )

  // LiveKit gọi onError cả khi KHÔNG KẾT NỐI ĐƯỢC lẫn khi không mở được mic / cam. Chỉ lỗi kết nối mới
  // làm hỏng cuộc họp; lỗi mic / cam thì vẫn ở trong phòng (bấm bật lại sau).
  const onError = useCallback(
    (e: Error) => {
      if (e instanceof ConnectionError) {
        useCall.getState().finish({ code, title: room.title, reason: 'lost', message: `Không kết nối được phòng họp: ${e.message}` })
      }
    },
    [code, room.title],
  )

  const audio = useMemo(
    () => (choices.audioEnabled ? { deviceId: choices.audioDeviceId || undefined } : false),
    [choices.audioEnabled, choices.audioDeviceId],
  )
  const video = useMemo(
    () => (choices.videoEnabled ? { deviceId: choices.videoDeviceId || undefined } : false),
    [choices.videoEnabled, choices.videoDeviceId],
  )

  return createPortal(
    <LiveKitRoom
      data-lk-theme="default"
      // Toàn màn hình như Google Meet: phủ lên cả thanh MeetFlow; class `dark` = luôn nền tối dù app đang
      // giao diện sáng. dvh = chiều cao THẬT đang nhìn thấy (trên điện thoại, 100vh tính cả phần bị thanh
      // địa chỉ che → thanh nút ở đáy bị khuất).
      // Thu nhỏ: khung ngoài "trong suốt" (display: contents, xem index.css), chỉ còn ô nổi bên trong.
      className={mode === 'full' ? 'mf-room dark fixed inset-0 z-[60] flex flex-col overflow-hidden' : 'mf-room mf-room-mini dark'}
      style={mode === 'full' ? { height: '100dvh' } : undefined}
      serverUrl={LIVEKIT_URL}
      token={session.token}
      connect
      audio={audio}
      video={video}
      options={LK_OPTIONS}
      onDisconnected={onDisconnected}
      onError={onError}
    >
      <LiveRoom initial={room} mode={mode} />
    </LiveKitRoom>,
    document.body,
  )
}
