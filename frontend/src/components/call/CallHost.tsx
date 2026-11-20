import { lazy, Suspense, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { hasUnsentAudio } from '../../lib/roomTrackUploader'
import { useAuth } from '../../stores/auth'
import { useCall } from '../../stores/call'
import { Spinner } from '../ui'
import CallEndedNotice from './CallEndedNotice'

// Phần cuộc họp kéo theo thư viện LiveKit (~700KB) → chỉ tải khi thật sự đang họp
const ActiveCall = lazy(() => import('../room/ActiveCall'))

/**
 * Nơi "giữ" cuộc họp Online Meeting cho cả ứng dụng (phương án B).
 *
 * Đặt ngoài danh sách trang nên đổi trang không làm nó bị gỡ ra:
 *   - đang ở /room/<mã> của cuộc họp → hiện toàn màn hình
 *   - đang ở trang khác (vuốt / bấm Quay lại, bấm vào bảng Kanban…) → thu nhỏ thành ô nổi ở góc
 * Cuộc họp chỉ kết thúc khi bấm Rời phòng, chủ phòng kết thúc, mất mạng, đăng xuất hoặc đóng / tải lại tab.
 */
export default function CallHost() {
  const token = useAuth((s) => s.token)
  const session = useCall((s) => s.session)
  const ended = useCall((s) => s.ended)
  const { pathname } = useLocation()

  // Đăng xuất → rời cuộc họp (gỡ kết nối) và quên thông báo cũ
  useEffect(() => {
    if (!token) useCall.getState().finish(null)
  }, [token])

  // Cảnh báo khi đóng tab / tải lại lúc đang họp hoặc còn ghi âm chưa gửi xong (ở BẤT KỲ trang nào)
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (useCall.getState().session || hasUnsentAudio()) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [])

  // Họp xong, rời khỏi trang phòng → quên "đã kết thúc" để lần sau mở link là màn hình chờ như mới
  const prevPath = useRef(pathname)
  useEffect(() => {
    const was = prevPath.current
    prevPath.current = pathname
    const e = useCall.getState().ended
    if (e && pathname !== was && was === `/room/${e.code}`) useCall.getState().clearEnded()
  }, [pathname])

  if (!token) return null
  const full = session ? pathname === `/room/${session.code}` : false
  return (
    <>
      {session && (
        <Suspense
          fallback={
            full ? (
              <div className="mf-room dark fixed inset-0 z-[60] flex items-center justify-center">
                <Spinner text="Đang vào phòng họp…" />
              </div>
            ) : null
          }
        >
          {/* Vé mới (vào lại phòng) → dựng kết nối mới */}
          <ActiveCall key={session.token} session={session} mode={full ? 'full' : 'mini'} />
        </Suspense>
      )}
      {!session && ended && pathname !== `/room/${ended.code}` && <CallEndedNotice ended={ended} />}
    </>
  )
}
