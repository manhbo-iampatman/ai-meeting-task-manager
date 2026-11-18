import { useEffect, useRef, useState } from 'react'
import type { User } from '../api/types'

const NAME = '__name__'

export type AssigneeValue = { assignee_id: number | null; assignee_name: string | null }

/**
 * Chọn người làm: một thành viên trong nhóm, HOẶC gõ tên người chưa có tài khoản (F20).
 * Tên gõ vào sẽ hiện trong danh sách "tên chưa có người nhận" của nhóm; người đó vào nhóm
 * rồi bấm nhận tên là việc chuyển sang tài khoản của họ (F21).
 */
export default function AssigneePicker({
  members,
  assigneeId,
  assigneeName,
  onChange,
  disabled,
  className = '',
}: {
  members: User[]
  assigneeId: number | null
  assigneeName: string | null
  onChange: (v: AssigneeValue) => void
  disabled?: boolean
  className?: string
}) {
  // Đang gõ tên: có tên chữ sẵn, hoặc vừa chọn mục "gõ tên" nhưng chưa gõ xong
  const [typing, setTyping] = useState(!assigneeId && !!assigneeName)
  const [name, setName] = useState(assigneeName ?? '')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setName(assigneeName ?? '')
    if (assigneeId) setTyping(false)
    else if (assigneeName) setTyping(true)
  }, [assigneeId, assigneeName])

  const commitName = () => {
    const v = name.trim()
    if (v && v !== (assigneeName ?? '')) onChange({ assignee_id: null, assignee_name: v })
    if (!v && !assigneeName) setTyping(false) // bỏ dở, chưa gõ gì → quay lại như cũ
  }

  const cls = `w-full rounded-lg border border-slate-300 bg-field px-2.5 py-1.5 text-sm outline-none focus:border-brand-500 disabled:bg-slate-50 ${className}`
  return (
    <div className="space-y-1.5">
      <select
        className={cls}
        disabled={disabled}
        value={typing ? NAME : (assigneeId ?? '')}
        onChange={(e) => {
          const v = e.target.value
          if (v === NAME) {
            setTyping(true)
            setTimeout(() => input.current?.focus(), 0)
            return
          }
          setTyping(false)
          onChange({ assignee_id: v ? Number(v) : null, assignee_name: null })
        }}
      >
        <option value="">— Chưa có người làm —</option>
        {members.map((m) => (
          <option key={m.id} value={m.id}>
            {m.full_name}
          </option>
        ))}
        <option value={NAME}>+ Người chưa có tài khoản (gõ tên)…</option>
      </select>
      {typing && (
        <input
          ref={input}
          value={name}
          disabled={disabled}
          maxLength={100}
          placeholder="Gõ tên, vd. Duy, Su…"
          onChange={(e) => setName(e.target.value)}
          onBlur={commitName}
          onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
          className={`${cls} border-dashed`}
          title="Người này chưa có tài khoản. Khi họ vào nhóm và bấm nhận tên, việc sẽ chuyển sang tài khoản của họ."
        />
      )}
    </div>
  )
}
