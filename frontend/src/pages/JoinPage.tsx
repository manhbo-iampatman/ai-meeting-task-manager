import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { joinWorkspace } from '../api/endpoints'
import { errorMessage } from '../lib/utils'
import { Spinner } from '../components/ui'

/** Mở link /join/<mã> → tự tham gia nhóm rồi chuyển vào trang nhóm. */
export default function JoinPage() {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const started = useRef(false) // tránh gọi 2 lần trong StrictMode

  useEffect(() => {
    if (started.current) return
    started.current = true
    joinWorkspace(code)
      .then((ws) => {
        qc.invalidateQueries({ queryKey: ['workspaces'] })
        navigate(`/workspaces/${ws.id}`, { replace: true })
      })
      .catch((err) => setError(errorMessage(err)))
  }, [code, navigate, qc])

  if (!error) return <Spinner text="Đang tham gia nhóm…" />
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <p className="text-rose-600">{error}</p>
      <Link to="/" className="mt-4 inline-block text-sm text-brand-600 hover:underline">
        Về trang nhóm
      </Link>
    </div>
  )
}
