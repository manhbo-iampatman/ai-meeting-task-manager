import { useEffect, useRef, useState, type RefObject } from 'react'
import { Pencil } from 'lucide-react'
import type { Segment } from '../../api/types'
import { formatClock } from '../../lib/utils'
import { Button } from '../ui'

/** Tìm đoạn đang phát: đoạn cuối cùng có start ≤ thời điểm hiện tại. */
function activeIndex(segments: Segment[], t: number): number {
  let idx = -1
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i].start
    if (s == null) return -1
    if (s <= t + 0.05) idx = i
    else break
  }
  return idx
}

/**
 * F12: hiển thị bản ghi theo từng đoạn có mốc thời gian.
 * - Bấm mốc thời gian → audio tua đến đó.
 * - Đoạn đang phát được tô sáng (lắng nghe sự kiện `timeupdate` của thẻ <audio>).
 * - Chế độ sửa: sửa lỗi nhận dạng (tên riêng, thuật ngữ) trước khi đưa cho AI tóm tắt.
 * - Cuộc họp Online Meeting: mỗi đoạn có tên người nói (sửa chữ không làm mất tên).
 */
export default function TranscriptView({
  segments,
  audioRef,
  editable,
  saving,
  onSave,
}: {
  segments: Segment[]
  audioRef: RefObject<HTMLAudioElement | null>
  editable: boolean
  saving: boolean
  onSave: (segments: Segment[]) => Promise<unknown>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Segment[]>(segments)
  const [current, setCurrent] = useState(-1)
  const [follow, setFollow] = useState(true)
  const itemRefs = useRef<(HTMLLIElement | null)[]>([])
  const hasTime = segments.some((s) => s.start != null)

  useEffect(() => {
    if (!editing) setDraft(segments)
  }, [segments, editing])

  // Theo dõi thời gian phát của audio để tô sáng đoạn tương ứng
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !hasTime) return
    const onTime = () => setCurrent(activeIndex(segments, audio.currentTime))
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('seeked', onTime)
    return () => {
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('seeked', onTime)
    }
  }, [audioRef, segments, hasTime])

  // Tự cuộn tới đoạn đang phát
  useEffect(() => {
    const audio = audioRef.current
    if (follow && current >= 0 && audio && !audio.paused && !editing) {
      itemRefs.current[current]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [current, follow, editing, audioRef])

  const seek = (t: number | null) => {
    const audio = audioRef.current
    if (!audio || t == null) return
    audio.currentTime = t
    void audio.play()
  }

  const wordCount = segments.reduce((n, s) => n + s.text.split(/\s+/).filter(Boolean).length, 0)

  return (
    <div className="glass rounded-2xl border">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <h2 className="font-semibold">Bản ghi</h2>
        <span className="text-xs text-slate-500">
          {segments.length} đoạn · {wordCount} từ
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {hasTime && !editing && (
            <label className="flex items-center gap-1 text-xs text-slate-600">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
              Tự cuộn theo audio
            </label>
          )}
          {editable && !editing && (
            <Button variant="secondary" onClick={() => setEditing(true)}>
              <Pencil aria-hidden="true" /> Sửa bản ghi
            </Button>
          )}
          {editing && (
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setDraft(segments)
                  setEditing(false)
                }}
                disabled={saving}
              >
                Hủy
              </Button>
              <Button onClick={() => onSave(draft).then(() => setEditing(false))} disabled={saving}>
                {saving ? 'Đang lưu…' : 'Lưu bản ghi'}
              </Button>
            </>
          )}
        </div>
      </div>

      {editing && (
        <p className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          Sửa các chỗ AI nghe nhầm (đặc biệt là <b>tên người</b> và <b>ngày tháng</b>) để bước tóm tắt & tạo đầu việc chính xác hơn.
          Xóa hết chữ trong 1 đoạn để bỏ đoạn đó.
        </p>
      )}

      <ul className="max-h-[60vh] divide-y divide-slate-50 overflow-y-auto">
        {(editing ? draft : segments).map((s, i) => (
          <li
            key={i}
            ref={(el) => {
              itemRefs.current[i] = el
            }}
            className={`flex gap-3 px-4 py-2 ${!editing && i === current ? 'bg-brand-50' : ''}`}
          >
            {s.start != null ? (
              <button
                type="button"
                onClick={() => seek(s.start)}
                className="mt-0.5 h-fit shrink-0 rounded px-1.5 py-0.5 font-mono text-xs text-brand-600 hover:bg-brand-100"
                title="Nghe đoạn này"
              >
                {formatClock(s.start)}
              </button>
            ) : (
              <span className="mt-0.5 w-6 shrink-0 text-right font-mono text-xs text-slate-400">{i + 1}</span>
            )}
            {editing ? (
              <div className="w-full">
                {s.speaker && <div className="mb-0.5 text-xs font-semibold text-brand-700">{s.speaker}</div>}
              <textarea
                value={s.text}
                rows={Math.max(1, Math.ceil(s.text.length / 90))}
                onChange={(e) => setDraft((d) => d.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                className="w-full resize-y rounded-md border border-slate-200 px-2 py-1 text-sm outline-none focus:border-brand-400"
              />
              </div>
            ) : (
              <p className={`text-sm leading-relaxed ${i === current ? 'text-slate-900' : 'text-slate-700'}`}>
                {/* Online Meeting: mỗi người ghi bằng mic của mình nên biết chắc ai nói câu này */}
                {s.speaker && <span className="font-semibold text-brand-700">{s.speaker}: </span>}
                {s.text}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
