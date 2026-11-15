import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createWorkspace, joinWorkspace, listWorkspaces } from '../api/endpoints'
import { Button, ErrorText, Input, Spinner } from '../components/ui'
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
      <h1 className="text-2xl font-bold">Nhóm của bạn</h1>
      <p className="mt-1 text-sm text-slate-500">Mỗi nhóm có thành viên, các bảng công việc và (sắp tới) các cuộc họp.</p>

      {isLoading ? (
        <Spinner />
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.map((ws) => (
            <Link
              key={ws.id}
              to={`/workspaces/${ws.id}`}
              className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow"
            >
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-semibold">{ws.name}</h2>
                {ws.my_role === 'owner' && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">Trưởng nhóm</span>
                )}
              </div>
              <p className="mt-3 text-sm text-slate-500">
                {ws.member_count} thành viên · {ws.board_count} bảng
              </p>
            </Link>
          ))}
          {data?.length === 0 && (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500 sm:col-span-2 lg:col-span-3">
              Bạn chưa ở nhóm nào. Hãy tạo nhóm mới hoặc dán link mời bên dưới.
            </p>
          )}
        </div>
      )}

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <form
          className="rounded-xl border border-slate-200 bg-white p-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (name.trim()) create.mutate(name.trim())
          }}
        >
          <h3 className="font-semibold">Tạo nhóm mới</h3>
          <p className="mb-3 text-xs text-slate-500">Bạn sẽ là trưởng nhóm. Nhóm mới có sẵn 1 bảng với 3 cột.</p>
          <div className="flex gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Nhóm KLTN" />
            <Button type="submit" disabled={create.isPending}>
              Tạo
            </Button>
          </div>
          <div className="mt-2">
            <ErrorText>{create.error && errorMessage(create.error)}</ErrorText>
          </div>
        </form>

        <form
          className="rounded-xl border border-slate-200 bg-white p-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (code.trim()) join.mutate(extractCode(code))
          }}
        >
          <h3 className="font-semibold">Tham gia nhóm</h3>
          <p className="mb-3 text-xs text-slate-500">Dán link mời hoặc mã mời trưởng nhóm gửi cho bạn.</p>
          <div className="flex gap-2">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Link hoặc mã mời" />
            <Button type="submit" variant="secondary" disabled={join.isPending}>
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
