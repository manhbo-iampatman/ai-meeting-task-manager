import { useEffect, useMemo, useState, type RefObject } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { pushToBoard, updateDraft } from '../../api/endpoints'
import type { BoardBrief, DraftInput, ExtractedTask, MeetingDetail, Priority, User } from '../../api/types'
import { errorMessage, formatClock, formatDate, PRIORITY } from '../../lib/utils'
import AssigneePicker from '../AssigneePicker'
import Avatar from '../Avatar'
import { Button, ErrorText } from '../ui'

const chip = 'rounded-full px-2 py-0.5 text-xs font-medium'
const field = 'rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-indigo-500'

/** Người làm (chế độ chỉ xem): ghép được tài khoản hay chưa, và vì sao chưa. */
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
        {t.assignee_match === 'claimed' && <span className="text-xs text-slate-400">(đã tự nhận tên)</span>}
      </span>
    )
  }
  if (t.assignee_match === 'ambiguous') {
    return (
      <span className={`${chip} bg-amber-100 text-amber-800`} title="Nhóm có nhiều người trùng tên này. Chọn người làm ở bước duyệt.">
        “{t.raw_assignee}” trùng nhiều thành viên
      </span>
    )
  }
  if (t.assignee_name) {
    return (
      <span
        className={`${chip} border border-dashed border-slate-400 bg-white text-slate-700`}
        title="Chưa có tài khoản. Người này vào nhóm và bấm nhận tên thì việc chuyển sang họ."
      >
        {t.assignee_name} · chưa có tài khoản
      </span>
    )
  }
  if (t.assignee_match === 'self')
    return (
      <span
        className={`${chip} bg-amber-100 text-amber-800`}
        title="Bản ghi không cho biết ai là người nói câu này, nên hệ thống không đoán. Chọn người làm ở bước duyệt."
      >
        Người nói tự nhận (“{t.raw_assignee}”)
      </span>
    )
  if (t.assignee_match === 'group') return <span className={`${chip} bg-slate-100 text-slate-600`}>Cả nhóm (“{t.raw_assignee}”)</span>
  return <span className={`${chip} bg-slate-100 text-slate-500`}>Chưa rõ người làm</span>
}

/** Gợi ý dưới ô chọn người làm: AI đã nghe được gì. */
function AiHint({ t }: { t: ExtractedTask }) {
  const raw = t.raw_assignee
  let msg: string | null = null
  if (t.assignee_match === 'self') msg = `AI nghe “${raw}”: người nói tự nhận việc, bản ghi không cho biết là ai.`
  else if (t.assignee_match === 'group') msg = `AI nghe “${raw}”: giao cho cả nhóm.`
  else if (t.assignee_match === 'ambiguous') msg = `“${raw}” trùng nhiều thành viên — hãy chọn đúng người.`
  else if ((t.assignee_match === 'fuzzy' || t.assignee_match === 'no_accent') && t.assignee) msg = `Ghép theo tên gần giống: AI nghe “${raw}”.`
  else if (t.assignee_match === 'claimed') msg = 'Người này đã tự nhận tên.'
  else if (!t.assignee && t.assignee_name)
    msg = `Chưa có tài khoản → giao theo tên “${t.assignee_name}”. Người đó vào nhóm và bấm nhận tên là việc chuyển sang họ.`
  return msg ? <p className="mt-1 text-[11px] leading-snug text-slate-500">{msg}</p> : null
}

function DueView({ t }: { t: ExtractedTask }) {
  if (t.due_date) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-slate-700">{formatDate(t.due_date)}</span>
        {t.due_text && <span className="text-xs text-slate-400">“{t.due_text}”</span>}
        {t.due_approximate && <ApproxChip />}
      </span>
    )
  }
  if (t.due_text) return <span className="text-xs text-amber-700">“{t.due_text}” · chưa đổi được sang ngày</span>
  return <span className="text-xs text-slate-400">Không nói hạn</span>
}

function ApproxChip() {
  return (
    <span
      className={`${chip} bg-amber-100 text-amber-800`}
      title="Cách nói không chỉ rõ ngày, hệ thống ước lượng theo quy ước (vd. cuối tuần = Chủ nhật). Hãy kiểm tra lại."
    >
      ước lượng
    </span>
  )
}

function Evidence({ t, onPlay }: { t: ExtractedTask; onPlay: ((sec: number) => void) | null }) {
  if (!t.evidence_quote) return null
  return (
    <div className={`rounded-lg px-3 py-2 text-sm ${t.evidence_found ? 'bg-slate-50 text-slate-600' : 'bg-rose-50 text-rose-700'}`}>
      <div className="flex items-start gap-2">
        {onPlay && t.evidence_start != null && (
          <button
            type="button"
            onClick={() => onPlay(t.evidence_start!)}
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
  )
}

/** Một đầu việc ở chế độ DUYỆT: tick, sửa tiêu đề / người làm / hạn / ưu tiên. Mỗi thay đổi lưu ngay. */
function DraftEditor({
  t,
  members,
  dupBoardId,
  busy,
  onSave,
  onPlay,
}: {
  t: ExtractedTask
  members: User[]
  dupBoardId: number | null
  busy: boolean
  onSave: (body: DraftInput) => void
  onPlay: ((sec: number) => void) | null
}) {
  const [title, setTitle] = useState(t.title)
  useEffect(() => setTitle(t.title), [t.title])
  const off = !t.selected

  return (
    <li className={`space-y-2 px-4 py-3 ${off ? 'bg-slate-50/70' : ''}`}>
      <div className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={t.selected}
          disabled={busy}
          onChange={(e) => onSave({ selected: e.target.checked })}
          className="mt-2 h-4 w-4 shrink-0 accent-indigo-600"
          title={t.selected ? 'Bỏ tick: không đưa việc này lên bảng' : 'Tick: đưa việc này lên bảng'}
        />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title.trim() !== t.title && onSave({ title: title.trim() })}
              onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
              maxLength={255}
              className={`min-w-0 flex-1 rounded-lg border border-transparent px-1.5 py-1 text-sm font-medium outline-none hover:border-slate-200 focus:border-indigo-400 ${off ? 'text-slate-400 line-through' : 'text-slate-900'}`}
            />
            {t.duplicate_of_task_id && (
              <span className={`${chip} bg-sky-100 text-sky-800`} title="Lần tóm tắt trước đã đẩy một việc giống hệt lên bảng">
                đã có trên bảng
                {dupBoardId && (
                  <Link to={`/boards/${dupBoardId}?task=${t.duplicate_of_task_id}`} className="ml-1 underline">
                    xem
                  </Link>
                )}
              </span>
            )}
            {t.status === 'rejected' && !t.selected && <span className={`${chip} bg-slate-200 text-slate-600`}>đã bỏ</span>}
          </div>

          <div className={`grid gap-3 sm:grid-cols-[1.4fr_1fr_0.8fr] ${off ? 'opacity-60' : ''}`}>
            <div>
              <p className="mb-1 text-xs text-slate-400">Ai làm</p>
              <AssigneePicker
                members={members}
                assigneeId={t.assignee?.id ?? null}
                assigneeName={t.assignee_name}
                disabled={busy}
                onChange={(v) => onSave(v)}
              />
              <AiHint t={t} />
            </div>
            <div>
              <p className="mb-1 text-xs text-slate-400">Hạn chót</p>
              <input
                type="date"
                value={t.due_date ?? ''}
                disabled={busy}
                onChange={(e) => onSave({ due_date: e.target.value || null })}
                className={`${field} w-full ${t.due_approximate ? 'border-amber-300 bg-amber-50' : ''}`}
              />
              <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-slate-500">
                {t.due_text && <span>AI nghe “{t.due_text}”</span>}
                {t.due_approximate && <ApproxChip />}
                {t.due_text && !t.due_date && <span className="text-amber-700">chưa đổi được sang ngày</span>}
              </div>
            </div>
            <div>
              <p className="mb-1 text-xs text-slate-400">Ưu tiên</p>
              <select
                value={t.priority}
                disabled={busy}
                onChange={(e) => onSave({ priority: e.target.value as Priority })}
                className={`${field} w-full`}
              >
                {(Object.keys(PRIORITY) as Priority[]).map((p) => (
                  <option key={p} value={p}>
                    {PRIORITY[p].label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <Evidence t={t} onPlay={onPlay} />
        </div>
      </div>
    </li>
  )
}

/** Một đầu việc ở chế độ CHỈ XEM (người không có quyền duyệt). */
function DraftReadOnly({ t, onPlay }: { t: ExtractedTask; onPlay: ((sec: number) => void) | null }) {
  return (
    <li className={`space-y-2 px-4 py-3 ${t.status === 'rejected' ? 'opacity-60' : ''}`}>
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-sm font-medium text-slate-900">{t.title}</p>
        {t.status === 'rejected' && <span className={`${chip} bg-slate-200 text-slate-600`}>đã bỏ</span>}
        <span className={`shrink-0 ${chip} ${PRIORITY[t.priority].className}`}>{PRIORITY[t.priority].label}</span>
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
            <DueView t={t} />
          </dd>
        </div>
      </dl>
      <Evidence t={t} onPlay={onPlay} />
    </li>
  )
}

/**
 * F14–F17: đầu việc AI tách từ cuộc họp.
 * - Trưởng nhóm / người tải cuộc họp lên: DUYỆT (tick, sửa) rồi "Đẩy lên bảng".
 * - Thành viên khác: chỉ xem.
 * Việc đã đẩy được giữ ở mục "Đã lên bảng" (truy vết, F18).
 */
export default function ExtractedTasksView({
  meeting,
  members,
  boards,
  audioRef,
  onChange,
}: {
  meeting: MeetingDetail
  members: User[]
  boards: BoardBrief[]
  audioRef: RefObject<HTMLAudioElement | null>
  onChange: (d: MeetingDetail) => void
}) {
  const qc = useQueryClient()
  const tasks = meeting.extracted_tasks
  const canReview = meeting.can_review
  const busy = meeting.status === 'summarizing'

  const todo = useMemo(
    () => [...tasks.filter((t) => t.status === 'pending'), ...tasks.filter((t) => t.status === 'rejected')],
    [tasks],
  )
  const pushed = tasks.filter((t) => t.status === 'accepted')
  const chosen = todo.filter((t) => t.selected)
  // Bảng chứa thẻ đã đẩy (để link "đã có trên bảng → xem")
  const boardOfTask = new Map(pushed.filter((t) => t.task_id).map((t) => [t.task_id!, t.task_board_id]))

  const [boardId, setBoardId] = useState<number | null>(null)
  const targetBoard = boardId ?? boards[0]?.id ?? null
  const [pushedMsg, setPushedMsg] = useState<{ n: number; board: BoardBrief } | null>(null)

  const save = useMutation({
    mutationFn: ({ id, body }: { id: number; body: DraftInput }) => updateDraft(id, body),
    onSuccess: onChange,
  })
  const push = useMutation({
    mutationFn: () => pushToBoard(meeting.id, targetBoard!),
    onSuccess: (d) => {
      onChange(d)
      const board = boards.find((b) => b.id === targetBoard)!
      setPushedMsg({ n: chosen.length, board })
      qc.invalidateQueries({ queryKey: ['board', targetBoard] })
      qc.invalidateQueries({ queryKey: ['pending-names', meeting.workspace_id] })
      qc.invalidateQueries({ queryKey: ['my-tasks'] })
    },
  })

  const play =
    meeting.has_audio && audioRef
      ? (t: number) => {
          const audio = audioRef.current
          if (!audio) return
          audio.currentTime = t
          void audio.play()
        }
      : null

  const warn = {
    noOne: chosen.filter((t) => !t.assignee && !t.assignee_name).length,
    approx: chosen.filter((t) => t.due_approximate).length,
    noEvidence: chosen.filter((t) => t.evidence_quote && !t.evidence_found).length,
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <h2 className="font-semibold">{canReview ? 'Duyệt đầu việc' : 'Đầu việc AI đề xuất'}</h2>
        <span className="text-xs text-slate-500">
          {todo.length} chờ duyệt{pushed.length > 0 && ` · ${pushed.length} đã lên bảng`}
        </span>
        <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
          {canReview ? 'Sửa, bỏ tick việc AI hiểu sai, rồi đẩy lên bảng' : 'Chỉ xem'}
        </span>
      </div>

      {pushedMsg && (
        <p className="border-b border-emerald-100 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
          ✓ Đã đẩy {pushedMsg.n} việc lên bảng “{pushedMsg.board.name}”.{' '}
          <Link to={`/boards/${pushedMsg.board.id}`} className="font-medium underline">
            Mở bảng →
          </Link>
        </p>
      )}

      {todo.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-slate-500">
          {pushed.length ? 'Không còn đầu việc nào chờ duyệt.' : 'AI không tìm thấy việc nào được giao trong cuộc họp này.'}
        </p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {todo.map((t) =>
            canReview ? (
              <DraftEditor
                key={t.id}
                t={t}
                members={members}
                dupBoardId={t.duplicate_of_task_id ? (boardOfTask.get(t.duplicate_of_task_id) ?? null) : null}
                busy={busy}
                onSave={(body) => save.mutate({ id: t.id, body })}
                onPlay={play}
              />
            ) : (
              <DraftReadOnly key={t.id} t={t} onPlay={play} />
            ),
          )}
        </ul>
      )}

      {canReview && todo.length > 0 && (
        <div className="space-y-2 border-t border-slate-100 bg-slate-50/60 px-4 py-3">
          {(warn.noOne > 0 || warn.approx > 0 || warn.noEvidence > 0) && (
            <p className="text-xs text-amber-700">
              Lưu ý trong các việc được chọn:
              {warn.noOne > 0 && ` ${warn.noOne} việc chưa có người làm (thẻ sẽ để trống người làm);`}
              {warn.approx > 0 && ` ${warn.approx} hạn chót là ước lượng;`}
              {warn.noEvidence > 0 && ` ${warn.noEvidence} việc không thấy câu gốc trong bản ghi;`}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-sm text-slate-600" htmlFor="push-board">
              Đẩy vào bảng
            </label>
            <select
              id="push-board"
              value={targetBoard ?? ''}
              onChange={(e) => setBoardId(Number(e.target.value))}
              className={field}
            >
              {boards.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
            <span className="text-xs text-slate-500">(cột đầu tiên)</span>
            <Button
              className="ml-auto"
              disabled={busy || push.isPending || chosen.length === 0 || !targetBoard}
              onClick={() => {
                const b = boards.find((x) => x.id === targetBoard)
                const skipped = todo.length - chosen.length
                const msg =
                  `Đẩy ${chosen.length} việc lên bảng “${b?.name}”?` +
                  (skipped ? `\n${skipped} việc bỏ tick sẽ được đánh dấu “đã bỏ” (vẫn đẩy lại được sau).` : '')
                if (confirm(msg)) push.mutate()
              }}
            >
              ⬆ Đẩy {chosen.length} việc lên bảng
            </Button>
          </div>
          <ErrorText>{(save.error || push.error) && errorMessage(save.error || push.error)}</ErrorText>
        </div>
      )}

      {pushed.length > 0 && (
        <details className="border-t border-slate-100" open={todo.length === 0}>
          <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium text-slate-700">
            ✓ Đã lên bảng ({pushed.length})
          </summary>
          <ul className="divide-y divide-slate-100 border-t border-slate-100">
            {pushed.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
                <span className="min-w-0 flex-1 text-slate-800">{t.title}</span>
                <span className="text-xs text-slate-500">
                  {t.assignee?.full_name ?? t.assignee_name ?? 'chưa có người làm'}
                  {t.due_date && ` · ${formatDate(t.due_date)}`}
                </span>
                {t.task_id && t.task_board_id ? (
                  <Link to={`/boards/${t.task_board_id}?task=${t.task_id}`} className="text-xs text-indigo-600 hover:underline">
                    Mở thẻ
                  </Link>
                ) : (
                  <span className="text-xs text-slate-400">thẻ đã bị xóa khỏi bảng</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
