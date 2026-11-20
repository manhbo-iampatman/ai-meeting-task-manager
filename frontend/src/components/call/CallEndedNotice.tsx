import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Video, X } from 'lucide-react'
import { hasUnsentAudio } from '../../lib/roomTrackUploader'
import { useCall, type CallEnd } from '../../stores/call'
import { Button } from '../ui'

const TEXT: Record<CallEnd['reason'], string> = {
  left: 'Bạn đã rời phòng họp',
  ended: 'Buổi họp đã kết thúc',
  lost: 'Mất kết nối với phòng họp',
}

/**
 * Cuộc họp đang thu nhỏ thì kết thúc / rớt mạng / mình bấm rời → báo bằng một thẻ nhỏ ở góc thay vì
 * kéo người dùng ra khỏi trang đang xem.
 */
export default function CallEndedNotice({ ended }: { ended: CallEnd }) {
  const navigate = useNavigate()
  const clear = useCall((s) => s.clearEnded)
  const [unsent, setUnsent] = useState(hasUnsentAudio())
  useEffect(() => {
    const t = window.setInterval(() => setUnsent(hasUnsentAudio()), 500)
    return () => window.clearInterval(t)
  }, [])

  // Tự bấm rời và ghi âm đã gửi xong → không cần làm gì thêm, tự ẩn sau vài giây
  useEffect(() => {
    if (ended.reason !== 'left' || unsent) return
    const t = window.setTimeout(clear, 4000)
    return () => window.clearTimeout(t)
  }, [ended.reason, unsent, clear])

  return (
    <div
      role="status"
      className="glass-blur fixed right-4 bottom-4 z-40 flex w-[min(22rem,calc(100vw-2rem))] animate-pop items-start gap-3 rounded-2xl border p-4 shadow-xl"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-100">
        <Video className="size-5 text-brand-600" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{TEXT[ended.reason]}</p>
        <p className="truncate text-xs text-slate-500">{ended.title}</p>
        {unsent && <p className="mt-1.5 text-xs text-amber-700">Đang gửi nốt ghi âm của bạn… đừng đóng tab này.</p>}
        {ended.message && <p className="mt-1.5 text-xs text-rose-600">{ended.message}</p>}
        {ended.reason !== 'left' && (
          <div className="mt-2.5">
            {/* Sang trang phòng: "lost" → màn hình chờ để vào lại; "ended" → kết quả buổi họp, link bản ghi */}
            <Button size="sm" onClick={() => navigate(`/room/${ended.code}`)}>
              {ended.reason === 'lost' ? 'Vào lại phòng' : 'Xem kết quả buổi họp'}
            </Button>
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={clear}
        className="-mt-1 -mr-1 flex size-8 shrink-0 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
        aria-label="Đóng thông báo"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </div>
  )
}
