import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addComment, deleteComment, deleteTask, getTask, moveTask, updateTask, type TaskInput } from '../../api/endpoints'
import type { BoardDetail, Priority } from '../../api/types'
import { canEditTask, NO_EDIT_REASON } from '../../lib/permissions'
import { errorMessage, formatClock, formatDate, formatDateTime, PRIORITY } from '../../lib/utils'
import { useAuth } from '../../stores/auth'
import AssigneePicker from '../AssigneePicker'
import Avatar from '../Avatar'
import Modal from '../Modal'
import { Button, ErrorText, Label, Spinner } from '../ui'

const selectCls =
  'w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm outline-none focus:border-indigo-500 disabled:bg-slate-50 disabled:text-slate-500'

/** Cửa sổ chi tiết công việc: sửa trực tiếp, mỗi thay đổi lưu ngay lên server. */
export default function TaskModal({ taskId, board, onClose }: { taskId: number; board: BoardDetail; onClose: () => void }) {
  const qc = useQueryClient()
  const me = useAuth((s) => s.user)!
  const { data: task, isLoading, error } = useQuery({ queryKey: ['task', taskId], queryFn: () => getTask(taskId) })

  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [comment, setComment] = useState('')

  useEffect(() => {
    if (task) {
      setTitle(task.title)
      setDesc(task.description ?? '')
    }
  }, [task?.id, task?.title, task?.description]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['task', taskId] })
    qc.invalidateQueries({ queryKey: ['board', board.id] })
  }
  const save = useMutation({ mutationFn: (body: TaskInput) => updateTask(taskId, body), onSuccess: refresh })
  const move = useMutation({ mutationFn: (columnId: number) => moveTask(taskId, columnId, 9999), onSuccess: refresh })
  const remove = useMutation({
    mutationFn: () => deleteTask(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['board', board.id] })
      onClose()
    },
  })
  const postComment = useMutation({
    mutationFn: () => addComment(taskId, comment.trim()),
    onSuccess: () => {
      setComment('')
      refresh()
    },
  })
  const removeComment = useMutation({ mutationFn: deleteComment, onSuccess: refresh })

  return (
    <Modal open onClose={onClose} wide>
      {isLoading && <Spinner />}
      {error && <p className="p-6 text-rose-600">{errorMessage(error, 'Không tìm thấy công việc')}</p>}
      {task && (() => {
        const editable = canEditTask(task, board.owner_id, me.id)
        return (
        <div className="p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title.trim() !== task.title && save.mutate({ title: title.trim() })}
              disabled={!editable}
              className="flex-1 rounded-lg border border-transparent px-2 py-1 text-lg font-semibold outline-none hover:border-slate-200 focus:border-indigo-400"
            />
            <button onClick={onClose} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Đóng">
              ✕
            </button>
          </div>
          <p className="px-2 text-xs text-slate-500">
            trong cột <b>{task.column_name}</b> · tạo lúc {formatDateTime(task.created_at)}
          </p>
          {!editable && (
            <p className="mx-2 mt-2 rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-600">
              🔒 {NO_EDIT_REASON}. Bạn vẫn xem và bình luận được.
            </p>
          )}

          <div className="mt-5 grid gap-6 md:grid-cols-[1fr_220px]">
            <div className="min-w-0">
              <Label>Mô tả</Label>
              <textarea
                rows={5}
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                onBlur={() => desc !== (task.description ?? '') && save.mutate({ description: desc || null })}
                placeholder={editable ? 'Thêm mô tả chi tiết…' : 'Chưa có mô tả'}
                disabled={!editable}
                className="w-full disabled:bg-slate-50 rounded-lg border border-slate-300 p-2.5 text-sm outline-none focus:border-indigo-500"
              />

              {task.source && (
                <div className="mt-4 rounded-lg border border-violet-100 bg-violet-50/60 p-3 text-sm">
                  <p className="text-xs text-violet-700">
                    🎙 Tạo từ cuộc họp{' '}
                    <Link to={`/meetings/${task.source.meeting_id}`} className="font-medium underline">
                      {task.source.meeting_title}
                    </Link>{' '}
                    ({formatDate(task.source.meeting_date)})
                    {task.source.evidence_start != null && ` · phút ${formatClock(task.source.evidence_start)}`}
                  </p>
                  {task.source.evidence_quote && (
                    <p className="mt-1 italic leading-relaxed text-slate-700">“{task.source.evidence_quote}”</p>
                  )}
                </div>
              )}

              <h4 className="mb-2 mt-5 text-sm font-semibold">Bình luận ({task.comments.length})</h4>
              <form
                className="flex gap-2"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault()
                  if (comment.trim()) postComment.mutate()
                }}
              >
                <Avatar user={me} />
                <input
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Viết bình luận…"
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-500"
                />
                <Button type="submit" disabled={postComment.isPending || !comment.trim()}>
                  Gửi
                </Button>
              </form>
              <ul className="mt-3 space-y-3">
                {[...task.comments].reverse().map((c) => (
                  <li key={c.id} className="flex gap-2">
                    <Avatar user={c.user} />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-slate-500">
                        <b className="text-slate-700">{c.user.full_name}</b> · {formatDateTime(c.created_at)}
                        {c.user.id === me.id && (
                          <button className="ml-2 text-rose-500 hover:underline" onClick={() => removeComment.mutate(c.id)}>
                            xóa
                          </button>
                        )}
                      </div>
                      <p className="mt-0.5 whitespace-pre-wrap rounded-lg bg-slate-50 px-3 py-2 text-sm">{c.content}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            <aside className="space-y-4">
              <div>
                <Label>Cột</Label>
                <select
                  className={selectCls}
                  value={task.column_id}
                  disabled={!editable}
                  onChange={(e) => move.mutate(Number(e.target.value))}
                >
                  {board.columns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label>Người làm</Label>
                <AssigneePicker
                  members={board.members}
                  assigneeId={task.assignee?.id ?? null}
                  assigneeName={task.assignee_name}
                  onChange={(v) => save.mutate(v)}
                  disabled={!editable}
                  className="!py-2"
                />
                {!task.assignee && task.assignee_name && (
                  <p className="mt-1 text-[11px] leading-snug text-slate-500">
                    Chưa có tài khoản. Khi “{task.assignee_name}” vào nhóm và nhận tên, việc sẽ chuyển sang họ.
                  </p>
                )}
              </div>
              <div>
                <Label>Hạn chót</Label>
                <input
                  type="date"
                  className={selectCls}
                  disabled={!editable}
                  value={task.due_date ?? ''}
                  onChange={(e) => save.mutate({ due_date: e.target.value || null })}
                />
              </div>
              <div>
                <Label>Mức ưu tiên</Label>
                <select
                  className={selectCls}
                  disabled={!editable}
                  value={task.priority}
                  onChange={(e) => save.mutate({ priority: e.target.value as Priority })}
                >
                  {(Object.keys(PRIORITY) as Priority[]).map((p) => (
                    <option key={p} value={p}>
                      {PRIORITY[p].label}
                    </option>
                  ))}
                </select>
              </div>
              <ErrorText>{(save.error || move.error) && errorMessage(save.error || move.error)}</ErrorText>
              {editable && (
                <Button
                  variant="secondary"
                  className="w-full !text-rose-600"
                  onClick={() => confirm('Xóa công việc này?') && remove.mutate()}
                >
                  Xóa công việc
                </Button>
              )}
            </aside>
          </div>
        </div>
        )
      })()}
    </Modal>
  )
}
