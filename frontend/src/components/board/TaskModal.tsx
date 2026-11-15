import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addComment, deleteComment, deleteTask, getTask, moveTask, updateTask, type TaskInput } from '../../api/endpoints'
import type { BoardDetail, Priority } from '../../api/types'
import { errorMessage, formatDateTime, PRIORITY } from '../../lib/utils'
import { useAuth } from '../../stores/auth'
import Avatar from '../Avatar'
import Modal from '../Modal'
import { Button, ErrorText, Label, Spinner } from '../ui'

const selectCls =
  'w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm outline-none focus:border-indigo-500'

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
      {task && (
        <div className="p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title.trim() !== task.title && save.mutate({ title: title.trim() })}
              className="flex-1 rounded-lg border border-transparent px-2 py-1 text-lg font-semibold outline-none hover:border-slate-200 focus:border-indigo-400"
            />
            <button onClick={onClose} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Đóng">
              ✕
            </button>
          </div>
          <p className="px-2 text-xs text-slate-500">
            trong cột <b>{task.column_name}</b> · tạo lúc {formatDateTime(task.created_at)}
          </p>

          <div className="mt-5 grid gap-6 md:grid-cols-[1fr_220px]">
            <div className="min-w-0">
              <Label>Mô tả</Label>
              <textarea
                rows={5}
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                onBlur={() => desc !== (task.description ?? '') && save.mutate({ description: desc || null })}
                placeholder="Thêm mô tả chi tiết…"
                className="w-full rounded-lg border border-slate-300 p-2.5 text-sm outline-none focus:border-indigo-500"
              />

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
                <select className={selectCls} value={task.column_id} onChange={(e) => move.mutate(Number(e.target.value))}>
                  {board.columns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label>Người làm</Label>
                <select
                  className={selectCls}
                  value={task.assignee?.id ?? ''}
                  onChange={(e) => save.mutate({ assignee_id: e.target.value ? Number(e.target.value) : null })}
                >
                  <option value="">— Chưa giao —</option>
                  {board.members.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.full_name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label>Hạn chót</Label>
                <input
                  type="date"
                  className={selectCls}
                  value={task.due_date ?? ''}
                  onChange={(e) => save.mutate({ due_date: e.target.value || null })}
                />
              </div>
              <div>
                <Label>Mức ưu tiên</Label>
                <select
                  className={selectCls}
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
              <Button
                variant="secondary"
                className="w-full !text-rose-600"
                onClick={() => confirm('Xóa công việc này?') && remove.mutate()}
              >
                Xóa công việc
              </Button>
            </aside>
          </div>
        </div>
      )}
    </Modal>
  )
}
