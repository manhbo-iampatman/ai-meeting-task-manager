import { useState } from 'react'
import { Mic, Pause, Play, Square } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useRecorder } from '../../hooks/useRecorder'
import { uploadRecording } from '../../lib/uploadRecording'
import { formatClock, formatDate, todayISO } from '../../lib/utils'
import Modal from '../Modal'
import { Button, ErrorText, Input, Label } from '../ui'

/** E1: ghi âm cuộc họp trực tiếp trên trình duyệt. */
export default function RecordMeetingModal({ workspaceId, onClose }: { workspaceId: number; onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const rec = useRecorder()
  const [date, setDate] = useState(todayISO())
  const [title, setTitle] = useState('')
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState('')

  const active = rec.state === 'recording' || rec.state === 'paused'
  const finalTitle = title.trim() || `Họp ngày ${formatDate(date)}`

  async function stopAndUpload() {
    const meta = await rec.stop()
    if (!meta) return
    setUploadError('')
    setUploadPct(0)
    try {
      const m = await uploadRecording(meta, setUploadPct)
      qc.invalidateQueries({ queryKey: ['meetings', workspaceId] })
      navigate(`/meetings/${m.id}`)
    } catch (e) {
      setUploadPct(null)
      setUploadError((e as Error).message)
      qc.invalidateQueries({ queryKey: ['pending-recordings', workspaceId] })
    }
  }

  const close = () => {
    if (active) return // đang ghi thì không cho đóng bằng nút Esc / bấm ra ngoài
    qc.invalidateQueries({ queryKey: ['pending-recordings', workspaceId] })
    onClose()
  }

  // 20 vạch mức âm lượng
  const bars = Array.from({ length: 20 }, (_, i) => i / 20 < rec.level)

  return (
    <Modal open onClose={close}>
      <div className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-semibold">Ghi âm cuộc họp</h2>
          <p className="text-sm text-slate-500">Đặt máy ở giữa bàn họp. Bản ghi được lưu liên tục trên máy, không sợ mất khi lỡ tắt trang.</p>
        </div>

        <div className="grid grid-cols-[1fr_auto] gap-3">
          <div>
            <Label>Tên cuộc họp</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={finalTitle} disabled={rec.state !== 'idle' && rec.state !== 'error'} />
          </div>
          <div>
            <Label>Ngày họp</Label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} disabled={rec.state !== 'idle' && rec.state !== 'error'} />
          </div>
        </div>

        {/* Khu vực ghi */}
        <div className="flex flex-col items-center gap-3 rounded-xl bg-slate-50 py-6">
          <div className={`font-mono text-4xl tabular-nums ${rec.state === 'recording' ? 'text-rose-600' : 'text-slate-700'}`}>
            {formatClock(rec.elapsed)}
          </div>
          <div className="flex h-6 items-end gap-0.5" aria-hidden>
            {bars.map((on, i) => (
              <span
                key={i}
                className={`w-1.5 rounded-sm transition-all ${on ? (i > 15 ? 'bg-rose-500' : 'bg-emerald-500') : 'bg-slate-200'}`}
                style={{ height: `${30 + (i / 20) * 70}%` }}
              />
            ))}
          </div>
          <p className="text-xs text-slate-500">
            {rec.state === 'idle' && 'Bấm nút đỏ để bắt đầu ghi'}
            {rec.state === 'requesting' && 'Đang xin quyền dùng micro… (hãy bấm "Cho phép")'}
            {rec.state === 'recording' && 'Đang ghi âm'}
            {rec.state === 'paused' && 'Đang tạm dừng'}
            {rec.state === 'stopped' && (uploadPct !== null ? `Đang tải lên… ${uploadPct}%` : 'Đã dừng ghi')}
          </p>

          <div className="flex items-center gap-3">
            {(rec.state === 'idle' || rec.state === 'error') && (
              <button
                onClick={() => rec.start({ workspaceId, title: finalTitle, meetingDate: date })}
                className="btn-danger flex size-16 items-center justify-center rounded-full transition duration-150 hover:scale-105 active:scale-95"
                aria-label="Bắt đầu ghi âm"
              >
                <Mic className="size-7" aria-hidden="true" />
              </button>
            )}
            {active && (
              <>
                <Button variant="secondary" onClick={rec.state === 'recording' ? rec.pause : rec.resume}>
                  {rec.state === 'recording' ? (
                    <>
                      <Pause aria-hidden="true" /> Tạm dừng
                    </>
                  ) : (
                    <>
                      <Play aria-hidden="true" /> Ghi tiếp
                    </>
                  )}
                </Button>
                <Button variant="danger" onClick={stopAndUpload}>
                  <Square aria-hidden="true" /> Dừng & xử lý
                </Button>
              </>
            )}
          </div>
        </div>

        {uploadPct !== null && (
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full bg-brand-500 transition-all" style={{ width: `${uploadPct}%` }} />
          </div>
        )}

        <ErrorText>{rec.error}</ErrorText>
        {rec.saveFailed && <ErrorText>Không lưu tạm được trên máy (bộ nhớ trình duyệt đầy?). Đừng tắt trang khi chưa tải lên xong.</ErrorText>}
        {uploadError && (
          <div className="space-y-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
            <p>
              <b>Chưa tải lên được:</b> {uploadError}
            </p>
            <p>Bản ghi <b>vẫn được giữ trên máy này</b>. Bạn có thể đóng hộp thoại, nó sẽ nằm trong mục "Bản ghi chưa tải lên" và tự tải lên khi có mạng.</p>
          </div>
        )}

        <div className="flex justify-end">
          <Button variant="ghost" onClick={close} disabled={active || uploadPct !== null}>
            {rec.state === 'stopped' ? 'Đóng' : 'Hủy'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
