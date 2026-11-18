import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { claimName, listPendingNames } from '../api/endpoints'
import type { PendingName } from '../api/types'
import { errorMessage, formatDate } from '../lib/utils'
import { Button, ErrorText } from './ui'

function summary(p: PendingName): string {
  const parts = []
  const waiting = p.drafts.filter((d) => d.status === 'pending').length
  const dropped = p.drafts.length - waiting
  if (p.tasks.length) parts.push(`${p.tasks.length} việc trên bảng`)
  if (waiting) parts.push(`${waiting} đầu việc chờ duyệt`)
  if (dropped) parts.push(`${dropped} đầu việc đã bỏ`)
  return parts.join(' · ')
}

function NameItem({ p, onClaim, busy }: { p: PendingName; onClaim: () => void; busy: boolean }) {
  const [open, setOpen] = useState(p.suggested)
  const others = p.variants.filter((v) => v !== p.name)
  return (
    <li className={`rounded-lg border p-3 ${p.suggested ? 'border-indigo-300 bg-white' : 'border-slate-200 bg-white'}`}>
      {p.suggested && (
        <p className="mb-1.5 text-xs font-medium text-indigo-700">
          Bạn có phải là “{p.name}” không? Tên này giống tên của bạn.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-dashed border-slate-400 px-2.5 py-0.5 text-sm font-medium text-slate-800">
          {p.name}
        </span>
        {others.length > 0 && <span className="text-xs text-slate-400">còn viết là: {others.join(', ')}</span>}
        <button className="text-xs text-slate-500 hover:underline" onClick={() => setOpen((o) => !o)}>
          {summary(p)} {open ? '▴' : '▾'}
        </button>
        <Button className="ml-auto" variant={p.suggested ? 'primary' : 'secondary'} disabled={busy} onClick={onClaim}>
          🙋 Đây là tôi
        </Button>
      </div>
      {open && (
        <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2 text-sm text-slate-600">
          {p.tasks.map((t) => (
            <li key={`t${t.id}`} className="flex flex-wrap gap-x-2">
              <Link to={`/boards/${t.board_id}?task=${t.id}`} className="text-slate-800 hover:underline">
                {t.title}
              </Link>
              <span className="text-xs text-slate-400">
                bảng {t.board_name}
                {t.due_date && ` · hạn ${formatDate(t.due_date)}`}
              </span>
            </li>
          ))}
          {p.drafts.map((d) => (
            <li key={`d${d.id}`} className="flex flex-wrap gap-x-2">
              <span className="text-slate-800">{d.title}</span>
              <Link to={`/meetings/${d.meeting_id}`} className="text-xs text-slate-400 hover:underline">
                {d.status === 'rejected' ? 'nháp đã bỏ' : 'nháp chờ duyệt'} · cuộc họp “{d.meeting_title}”
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

/**
 * F21 — Tên chưa có người nhận. Trong họp người ta hay gọi bằng biệt danh / tên thân mật,
 * máy không biết đó là ai → để chính người đó bấm "Đây là tôi".
 * Thành viên CHƯA nhận tên mới thấy danh sách; nhận xong thì ẩn (bị hoàn tác thì thấy lại).
 */
export default function PendingNamesSection({ workspaceId }: { workspaceId: number }) {
  const qc = useQueryClient()
  const [done, setDone] = useState('')
  const { data } = useQuery({
    queryKey: ['pending-names', workspaceId],
    queryFn: () => listPendingNames(workspaceId),
  })
  const claim = useMutation({
    mutationFn: (key: string) => claimName(workspaceId, key),
    onSuccess: (c) => {
      setDone(
        `Đã nhận tên “${c.name}”. Các việc mang tên này giờ là của bạn` +
          (c.added_nickname ? `, và “${c.added_nickname}” đã thành biệt danh của bạn để lần sau AI tự nhận ra.` : '.'),
      )
      qc.invalidateQueries({ queryKey: ['pending-names', workspaceId] })
      qc.invalidateQueries({ queryKey: ['workspace', workspaceId] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
      qc.invalidateQueries({ queryKey: ['my-tasks'] })
    },
  })

  if (!data?.length && !done) return null
  return (
    <section className="mb-6 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
      <h2 className="font-semibold text-amber-900">Tên chưa có người nhận {data?.length ? `(${data.length})` : ''}</h2>
      <p className="mt-0.5 text-xs text-amber-800/80">
        Các tên được nhắc trong cuộc họp (hoặc gõ tay trên bảng) mà chưa khớp tài khoản nào — thường là biệt danh, tên
        thân mật. Nếu là bạn, bấm <b>Đây là tôi</b>: việc chuyển sang tài khoản của bạn ngay, trưởng nhóm sẽ được báo.
      </p>
      {done && <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">✓ {done}</p>}
      <ul className="mt-3 space-y-2">
        {data?.map((p) => (
          <NameItem
            key={p.key}
            p={p}
            busy={claim.isPending}
            onClaim={() => {
              const msg =
                `Nhận tên “${p.name}”?\n\n${summary(p)} sẽ chuyển sang tài khoản của bạn, ` +
                `và “${p.name}” thành biệt danh của bạn trong nhóm.\nTrưởng nhóm sẽ được thông báo và có thể hoàn tác nếu nhận nhầm.`
              if (confirm(msg)) claim.mutate(p.key)
            }}
          />
        ))}
      </ul>
      <div className="mt-2">
        <ErrorText>{claim.error && errorMessage(claim.error)}</ErrorText>
      </div>
    </section>
  )
}
