import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addMember,
  createBoard,
  deleteWorkspace,
  getWorkspace,
  regenerateInvite,
  removeMember,
  renameWorkspace,
  updateMember,
} from '../api/endpoints'
import type { Member, WorkspaceDetail } from '../api/types'
import Avatar from '../components/Avatar'
import MeetingsSection from '../components/meeting/MeetingsSection'
import PendingNamesSection from '../components/PendingNamesSection'
import { Button, ErrorText, Input, Spinner } from '../components/ui'
import { errorMessage } from '../lib/utils'
import { useAuth } from '../stores/auth'

function NicknameEditor({ ws, member, canEdit }: { ws: WorkspaceDetail; member: Member; canEdit: boolean }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(member.nicknames.join(', '))
  const save = useMutation({
    mutationFn: () =>
      updateMember(
        ws.id,
        member.user.id,
        value.split(',').map((s) => s.trim()).filter(Boolean),
      ),
    onSuccess: () => {
      setEditing(false)
      qc.invalidateQueries({ queryKey: ['workspace', ws.id] })
    },
  })

  if (editing) {
    return (
      <form
        className="mt-1 flex gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="VD: Nam, anh Nam, Nam béo" autoFocus />
        <Button type="submit" disabled={save.isPending}>
          Lưu
        </Button>
        <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
          Hủy
        </Button>
      </form>
    )
  }
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {member.nicknames.map((n) => (
        <span key={n} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
          {n}
        </span>
      ))}
      {member.nicknames.length === 0 && <span className="text-xs text-slate-400">Chưa có biệt danh</span>}
      {canEdit && (
        <button
          className="text-xs text-indigo-600 hover:underline"
          onClick={() => {
            setValue(member.nicknames.join(', '))
            setEditing(true)
          }}
        >
          Sửa
        </button>
      )}
    </div>
  )
}

export default function WorkspacePage() {
  const id = Number(useParams().id)
  const me = useAuth((s) => s.user)!
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data: ws, isLoading, error } = useQuery({ queryKey: ['workspace', id], queryFn: () => getWorkspace(id) })

  const [boardName, setBoardName] = useState('')
  const [email, setEmail] = useState('')
  const [copied, setCopied] = useState(false)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['workspace', id] })
    qc.invalidateQueries({ queryKey: ['workspaces'] })
  }
  const newBoard = useMutation({
    mutationFn: () => createBoard(id, boardName.trim()),
    onSuccess: (b) => {
      setBoardName('')
      refresh()
      navigate(`/boards/${b.id}`)
    },
  })
  const add = useMutation({
    mutationFn: () => addMember(id, email.trim()),
    onSuccess: () => {
      setEmail('')
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (userId: number) => removeMember(id, userId), onSuccess: refresh })
  const regen = useMutation({ mutationFn: () => regenerateInvite(id), onSuccess: refresh })
  const rename = useMutation({ mutationFn: (name: string) => renameWorkspace(id, name), onSuccess: refresh })
  const del = useMutation({
    mutationFn: () => deleteWorkspace(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      navigate('/')
    },
  })

  if (isLoading) return <Spinner />
  if (error || !ws) return <p className="p-8 text-center text-rose-600">{errorMessage(error, 'Không tìm thấy nhóm')}</p>

  const isOwner = ws.my_role === 'owner'
  const inviteLink = `${window.location.origin}/join/${ws.invite_code}`

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8">
      <Link to="/" className="text-sm text-slate-500 hover:underline">
        ← Nhóm của bạn
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{ws.name}</h1>
        {isOwner && (
          <button
            className="text-sm text-indigo-600 hover:underline"
            onClick={() => {
              const name = prompt('Tên nhóm mới', ws.name)
              if (name?.trim()) rename.mutate(name.trim())
            }}
          >
            Đổi tên
          </button>
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_380px]">
        {/* ---- Bảng công việc ---- */}
        <section>
          <PendingNamesSection workspaceId={ws.id} />
          <h2 className="mb-3 font-semibold">Bảng công việc</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {ws.boards.map((b) => (
              <Link
                key={b.id}
                to={`/boards/${b.id}`}
                className="rounded-xl border border-slate-200 bg-white p-4 font-medium shadow-sm hover:border-indigo-300"
              >
                📋 {b.name}
              </Link>
            ))}
          </div>
          <form
            className="mt-3 flex max-w-md gap-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              if (boardName.trim()) newBoard.mutate()
            }}
          >
            <Input value={boardName} onChange={(e) => setBoardName(e.target.value)} placeholder="Tên bảng mới" />
            <Button type="submit" variant="secondary" disabled={newBoard.isPending}>
              + Thêm bảng
            </Button>
          </form>

          <MeetingsSection workspaceId={ws.id} />
        </section>

        {/* ---- Thành viên ---- */}
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="font-semibold">Thành viên ({ws.members.length})</h2>
          <p className="mb-3 text-xs text-slate-500">
            Biệt danh giúp AI nhận ra ai được giao việc khi nghe cuộc họp (VD: “anh Nam”, “Nam béo”).
          </p>
          <ul className="divide-y divide-slate-100">
            {ws.members.map((m) => (
              <li key={m.user.id} className="flex gap-3 py-3">
                <Avatar user={m.user} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{m.user.full_name}</span>
                    {m.role === 'owner' && (
                      <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-700">Trưởng nhóm</span>
                    )}
                    {m.user.id === me.id && <span className="text-[11px] text-slate-400">(bạn)</span>}
                  </div>
                  <div className="truncate text-xs text-slate-500">{m.user.email}</div>
                  <NicknameEditor ws={ws} member={m} canEdit={isOwner || m.user.id === me.id} />
                </div>
                {m.role !== 'owner' && (isOwner || m.user.id === me.id) && (
                  <button
                    className="self-start text-xs text-rose-600 hover:underline"
                    onClick={() => {
                      const self = m.user.id === me.id
                      if (confirm(self ? 'Rời khỏi nhóm này?' : `Xóa ${m.user.full_name} khỏi nhóm?`)) {
                        remove.mutate(m.user.id, { onSuccess: () => self && navigate('/') })
                      }
                    }}
                  >
                    {m.user.id === me.id ? 'Rời nhóm' : 'Xóa'}
                  </button>
                )}
              </li>
            ))}
          </ul>

          {/* Mời thành viên */}
          <div className="mt-4 border-t border-slate-100 pt-4">
            <h3 className="text-sm font-semibold">Mời bằng link</h3>
            <div className="mt-2 flex gap-2">
              <Input readOnly value={inviteLink} onFocus={(e) => e.target.select()} className="text-xs" />
              <Button
                variant="secondary"
                onClick={async () => {
                  await navigator.clipboard.writeText(inviteLink)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1500)
                }}
              >
                {copied ? 'Đã chép' : 'Chép'}
              </Button>
            </div>
            {isOwner && (
              <button
                className="mt-1 text-xs text-slate-500 hover:underline"
                onClick={() => confirm('Đổi mã mời? Link cũ sẽ không dùng được nữa.') && regen.mutate()}
              >
                Đổi mã mời
              </button>
            )}

            {isOwner && (
              <form
                className="mt-4"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault()
                  if (email.trim()) add.mutate()
                }}
              >
                <h3 className="text-sm font-semibold">Thêm bằng email</h3>
                <p className="mb-2 text-xs text-slate-500">Người đó phải đã có tài khoản.</p>
                <div className="flex gap-2">
                  <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@example.com" />
                  <Button type="submit" disabled={add.isPending}>
                    Thêm
                  </Button>
                </div>
                <div className="mt-2">
                  <ErrorText>{add.error && errorMessage(add.error)}</ErrorText>
                </div>
              </form>
            )}
          </div>

          {isOwner && (
            <button
              className="mt-6 text-xs text-rose-600 hover:underline"
              onClick={() => confirm(`Xóa nhóm “${ws.name}” cùng TOÀN BỘ bảng và công việc? Không thể hoàn tác.`) && del.mutate()}
            >
              Xóa nhóm
            </button>
          )}
        </section>
      </div>
    </div>
  )
}
