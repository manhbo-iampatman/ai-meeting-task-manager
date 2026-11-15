import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { login, register } from '../api/endpoints'
import { Button, ErrorText, Input, Label } from '../components/ui'
import { errorMessage } from '../lib/utils'
import { useAuth } from '../stores/auth'

/** Dùng chung cho Đăng nhập và Đăng ký (mode). */
export default function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { token, setAuth } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (token) return <Navigate to={from} replace />

  const isLogin = mode === 'login'

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = isLogin ? await login({ email, password }) : await register({ email, password, full_name: fullName })
      setAuth(res.access_token, res.user)
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600 text-xl font-bold text-white">
            M
          </div>
          <h1 className="text-2xl font-bold">{isLogin ? 'Đăng nhập' : 'Tạo tài khoản'}</h1>
          <p className="mt-1 text-sm text-slate-500">Quản lý công việc nhóm · AI tóm tắt cuộc họp</p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {!isLogin && (
            <div>
              <Label>Họ và tên</Label>
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} required autoFocus placeholder="Nguyễn Văn Nam" />
            </div>
          )}
          <div>
            <Label>Email</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus={isLogin} placeholder="ban@example.com" />
          </div>
          <div>
            <Label>Mật khẩu</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={isLogin ? undefined : 6}
              placeholder={isLogin ? '' : 'Tối thiểu 6 ký tự'}
            />
          </div>
          <ErrorText>{error}</ErrorText>
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? 'Đang xử lý…' : isLogin ? 'Đăng nhập' : 'Đăng ký'}
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-600">
          {isLogin ? 'Chưa có tài khoản? ' : 'Đã có tài khoản? '}
          <Link to={isLogin ? '/register' : '/login'} state={location.state} className="font-medium text-indigo-600 hover:underline">
            {isLogin ? 'Đăng ký' : 'Đăng nhập'}
          </Link>
        </p>
      </div>
    </div>
  )
}
