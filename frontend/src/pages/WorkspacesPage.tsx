import { useState, type FormEvent } from 'react'
import { ArrowUpRight, LogIn, Plus, SquareKanban, Users } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createWorkspace, joinWorkspace, listWorkspaces } from '../api/endpoints'
import { Button, ErrorText, Input, Skeleton } from '../components/ui'
import { errorMessage } from '../lib/utils'

/** Lấy mã mời từ chuỗi người dùng dán vào (có thể là cả link /join/<mã>). */
function extractCode(input: string): string {
  const m = input.trim().match(/join\/([^/?#\s]+)/)
  return m ? m[1] : input.trim()
}

export default function WorkspacesPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data, isLoading } = useQuery({ queryKey: ['workspaces'], queryFn: listWorkspaces })
  const [name, setName] = useState('')
  const [code, setCode] = useState('')

  const create = useMutation({
    mutationFn: createWorkspace,
    onSuccess: (ws) => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/workspaces/${ws.id}`)
    },
  })
  const join = useMutation({
    mutationFn: joinWorkspace,
    onSuccess: (ws) => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      navigate(`/workspaces/${ws.id}`)
    },
  })

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8">
      <h1 className="text-3xl font-bold tracking-tight">Nhóm của bạn</h1>
      <p className="mt-1.5 text-sm text-slate-500">Mỗi nhóm có thành viên, các bảng công việc và các cuộc họp.</p>

      {isLoading ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label="Đang tải danh sách nhóm">
          <Skeleton className="h-28 !rounded-2xl" />
          <Skeleton className="h-28 !rounded-2xl" />
          <Skeleton className="h-28 !rounded-2xl" />
        </div>
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.map((ws) => (
            <Link
              key={ws.id}
              to={`/workspaces/${ws.id}`}
              className="lift glass group rounded-2xl border p-5 hover:border-brand-300"
            >
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-100 text-brand-700 transition-transform duration-200 group-hover:scale-110">
                  <Users className="size-5" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-semibold">{ws.name}</h2>
                  {ws.my_role === 'owner' && <span className="text-xs font-medium text-brand-600">Trưởng nhóm</span>}
                </div>
                <ArrowUpRight className="size-4 text-slate-400 transition group-hover:text-brand-600" aria-hidden="true" />
              </div>
              <p className="mt-4 flex items-center gap-3 text-sm text-slate-500">
                <span className="inline-flex items-center gap-1">
                  <Users className="size-3.5" aria-hidden="true" /> {ws.member_count} thành viên
                </span>
                <span className="inline-flex items-center gap-1">
                  <SquareKanban className="size-3.5" aria-hidden="true" /> {ws.board_count} bảng
                </span>
              </p>
            </Link>
          ))}
          {data?.length === 0 && (
            <p className="rounded-2xl border-2 border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 sm:col-span-2 lg:col-span-3">
              Bạn chưa ở nhóm nào. Hãy tạo nhóm mới hoặc dán link mời bên dưới.
            </p>
          )}
        </div>
      )}

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <form
          className="glass rounded-2xl border p-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (name.trim()) create.mutate(name.trim())
          }}
        >
          <h3 className="flex items-center gap-2 font-semibold">
            <Plus className="size-4 text-brand-600" aria-hidden="true" /> Tạo nhóm mới
          </h3>
          <p className="mb-3 text-xs text-slate-500">Bạn sẽ là trưởng nhóm. Nhóm mới có sẵn 1 bảng với 3 cột.</p>
          <div className="flex gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nhóm KLTN" aria-label="Tên nhóm mới" />
            <Button type="submit" loading={create.isPending}>
              Tạo
            </Button>
          </div>
          <div className="mt-2">
            <ErrorText>{create.error && errorMessage(create.error)}</ErrorText>
          </div>
        </form>

        <form
          className="glass rounded-2xl border p-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (code.trim()) join.mutate(extractCode(code))
          }}
        >
          <h3 className="flex items-center gap-2 font-semibold">
            <LogIn className="size-4 text-brand-600" aria-hidden="true" /> Tham gia nhóm
          </h3>
          <p className="mb-3 text-xs text-slate-500">Dán link mời hoặc mã mời trưởng nhóm gửi cho bạn.</p>
          <div className="flex gap-2">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Link hoặc mã mời" aria-label="Link hoặc mã mời" />
            <Button type="submit" variant="secondary" loading={join.isPending}>
              Tham gia
            </Button>
          </div>
          <div className="mt-2">
            <ErrorText>{join.error && errorMessage(join.error)}</ErrorText>
          </div>
        </form>
      </div>
    </div>
  )
}
