import type { RefObject } from 'react'
import type { ExtractedTask } from '../../api/types'
import { PRIORITY, formatClock, formatDate } from '../../lib/utils'
import Avatar from '../Avatar'

/** Người làm: hiện rõ hệ thống ghép được tài khoản hay chưa, và vì sao chưa. */
function Assignee({ t }: { t: ExtractedTask }) {
  if (t.assignee) {
    const heard = t.assignee_match === 'fuzzy' || t.assignee_match === 'no_accent'
    return (
      <span className="inline-flex items-center gap-1.5">
        <Avatar user={t.assignee} size="sm" />
        <span className="text-slate-700">{t.assignee.full_name}</span>
        {heard && (
          <span className="text-xs text-amber-600" title="Tên trong bản ghi không trùng hẳn, hệ thống ghép theo tên gần giống nhất">
            (nghe là “{t.raw_assignee}”)
          </span>
        )}
      </span>
    )
  }
  const chip = 'rounded-full px-2 py-0.5 text-xs font-medium'
  switch (t.assignee_match) {
    case 'self':
      return (
        <span
          className={`${chip} bg-amber-100 text-amber-800`}
          title="Bản ghi không cho biết ai là người nói câu này, nên hệ thống không đoán. Chọn người làm ở bước duyệt."
        >
          Người nói tự nhận (“{t.raw_assignee}”)
        </span>
      )
    case 'ambiguous':
      return (
        <span className={`${chip} bg-amber-100 text-amber-800`} title="Nhóm có nhiều người trùng tên này. Chọn người làm ở bước duyệt.">
          “{t.raw_assignee}” trùng nhiều thành viên
        </span>
      )
    case 'group':
      return <span className={`${chip} bg-slate-100 text-slate-600`}>Cả nhóm (“{t.raw_assignee}”)</span>
    default:
      return t.raw_assignee ? (
        <span className={`${chip} bg-slate-100 text-slate-600`} title="Tên này chưa khớp với thành viên nào trong nhóm">
          {t.raw_assignee} · chưa có tài khoản
        </span>
      ) : (
        <span className={`${chip} bg-slate-100 text-slate-500`}>Chưa rõ người làm</span>
      )
  }
}

function Due({ t }: { t: ExtractedTask }) {
  if (t.due_date) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-slate-700">{formatDate(t.due_date)}</span>
        {t.due_text && <span className="text-xs text-slate-400">“{t.due_text}”</span>}
        {t.due_approximate && (
          <span
            className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
            title="Cách nói không chỉ rõ ngày, hệ thống ước lượng theo quy ước (vd. cuối tuần = Chủ nhật). Hãy kiểm tra lại."
          >
            ước lượng
          </span>
        )}
      </span>
    )
  }
  if (t.due_text) return <span className="text-xs text-amber-700">“{t.due_text}” · chưa đổi được sang ngày</span>
  return <span className="text-xs text-slate-400">Không nói hạn</span>
}

/**
 * F14–F16: danh sách đầu việc NHÁP do AI trích từ cuộc họp (chỉ xem).
 * Sửa / bỏ / đẩy lên bảng Kanban là việc của màn hình duyệt (Giai đoạn 5).
 */
export default function ExtractedTasksView({
  tasks,
  audioRef,
  hasAudio,
}: {
  tasks: ExtractedTask[]
  audioRef: RefObject<HTMLAudioElement | null>
  hasAudio: boolean
}) {
  const play = (t: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = t
    void audio.play()
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <h2 className="font-semibold">Đầu việc AI đề xuất</h2>
        <span className="text-xs text-slate-500">{tasks.length} việc</span>
        <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">Bản nháp · chưa lên bảng</span>
      </div>

      {tasks.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-slate-500">AI không tìm thấy việc nào được giao trong cuộc họp này.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {tasks.map((t) => (
            <li key={t.id} className="space-y-2 px-4 py-3">
              <div className="flex items-start gap-2">
                <p className="min-w-0 flex-1 text-sm font-medium text-slate-900">{t.title}</p>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${PRIORITY[t.priority].className}`}>
                  {PRIORITY[t.priority].label}
                </span>
              </div>

              <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                <div className="flex items-center gap-2">
                  <dt className="shrink-0 text-xs text-slate-400">Ai làm</dt>
                  <dd className="min-w-0">
                    <Assignee t={t} />
                  </dd>
                </div>
                <div className="flex items-center gap-2">
                  <dt className="shrink-0 text-xs text-slate-400">Hạn</dt>
                  <dd className="min-w-0">
                    <Due t={t} />
                  </dd>
                </div>
              </dl>

              {t.evidence_quote && (
                <div className={`rounded-lg px-3 py-2 text-sm ${t.evidence_found ? 'bg-slate-50 text-slate-600' : 'bg-rose-50 text-rose-700'}`}>
                  <div className="flex items-start gap-2">
                    {hasAudio && t.evidence_start != null && (
                      <button
                        type="button"
                        onClick={() => play(t.evidence_start!)}
                        className="mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-mono text-xs text-indigo-600 hover:bg-indigo-100"
                        title="Nghe lại câu này"
                      >
                        ▶ {formatClock(t.evidence_start)}
                      </button>
                    )}
                    <p className="italic leading-relaxed">“{t.evidence_quote}”</p>
                  </div>
                  {!t.evidence_found && (
                    <p className="mt-1 text-xs font-medium not-italic">
                      ⚠ Không tìm thấy câu này trong bản ghi — có thể AI suy diễn. Hãy kiểm tra kỹ trước khi duyệt.
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
        Đây mới là đề xuất của AI. Sửa, bỏ bớt và đẩy lên bảng công việc được làm ở bước duyệt (Giai đoạn 5).
      </p>
    </div>
  )
}
