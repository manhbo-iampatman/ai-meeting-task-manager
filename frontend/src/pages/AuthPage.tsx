import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Mic, Sparkles, SquareKanban, type LucideIcon } from 'lucide-react'
import { login, register } from '../api/endpoints'
import Logo from '../components/Logo'
import ThemeToggle from '../components/ThemeToggle'
import { Button, ErrorText, Input, Label } from '../components/ui'
import { errorMessage } from '../lib/utils'
import { useAuth } from '../stores/auth'

// Ba bước cốt lõi của sản phẩm — người mới nhìn là hiểu MeetFlow làm gì
const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Mic, title: 'Ghi lại cuộc họp', text: 'Tải file ghi âm, ghi trực tiếp, hoặc họp ngay trong phòng Online Meeting.' },
  { icon: Sparkles, title: 'AI viết biên bản', text: 'Chuyển giọng nói thành văn bản, tóm tắt và tách ra ai làm gì, hạn khi nào.' },
  { icon: SquareKanban, title: 'Việc lên bảng', text: 'Duyệt rồi đẩy lên bảng Kanban của nhóm để giao việc và theo dõi tiến độ.' },
]

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
    <div className="relative flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="absolute right-3 top-3">
        <ThemeToggle />
      </div>

      <div className="grid w-full max-w-5xl animate-page items-center gap-10 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
        {/* Cột giới thiệu — chỉ hiện trên màn hình rộng */}
        <section className="hidden lg:block">
          <div className="flex items-center gap-3">
            <Logo size="lg" />
            <span className="text-gradient text-2xl font-bold tracking-tight">MeetFlow</span>
          </div>
          <h1 className="mt-8 text-4xl font-bold leading-[1.15] tracking-tight text-slate-900">
            Họp xong là <span className="text-gradient">có việc để làm</span>, không phải có thêm biên bản để quên.
          </h1>
          <p className="mt-4 max-w-md text-base leading-relaxed text-slate-600">
            Quản lý công việc nhóm tích hợp AI: tự tóm tắt cuộc họp và biến lời giao việc thành thẻ công việc có người làm, có hạn chót.
          </p>
          <ol className="mt-8 space-y-4">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <li key={title} className="flex animate-page gap-4" style={{ animationDelay: `${120 + i * 90}ms` }}>
                <span className="glass flex size-11 shrink-0 items-center justify-center rounded-2xl border text-brand-600">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <div>
                  <p className="font-semibold text-slate-800">{title}</p>
                  <p className="text-sm leading-relaxed text-slate-500">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* Biểu mẫu */}
        <section className="mx-auto w-full max-w-sm">
          <div className="mb-6 text-center lg:hidden">
            <div className="mb-3 flex justify-center">
              <Logo size="lg" />
            </div>
            <p className="text-sm text-slate-500">Quản lý công việc nhóm · AI tóm tắt cuộc họp</p>
          </div>

          <form onSubmit={onSubmit} className="glass space-y-4 rounded-3xl border p-6 sm:p-7">
            <div>
              <h2 className="text-xl font-bold tracking-tight">{isLogin ? 'Đăng nhập' : 'Tạo tài khoản'}</h2>
              <p className="mt-1 text-sm text-slate-500">
                {isLogin ? 'Chào mừng bạn quay lại.' : 'Mất khoảng 10 giây, không cần xác minh email.'}
              </p>
            </div>
            {!isLogin && (
              <div>
                <Label htmlFor="auth-name">Họ và tên</Label>
                <Input
                  id="auth-name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  autoFocus
                  autoComplete="name"
                  placeholder="Nguyễn Văn Nam"
                />
              </div>
            )}
            <div>
              <Label htmlFor="auth-email">Email</Label>
              <Input
                id="auth-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus={isLogin}
                autoComplete="email"
                placeholder="ban@example.com"
              />
            </div>
            <div>
              <Label htmlFor="auth-password">Mật khẩu</Label>
              <Input
                id="auth-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={isLogin ? undefined : 6}
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                placeholder={isLogin ? '' : 'Tối thiểu 6 ký tự'}
              />
            </div>
            <ErrorText>{error}</ErrorText>
            <Button type="submit" loading={loading} className="w-full !py-2.5">
              {isLogin ? 'Đăng nhập' : 'Đăng ký'}
            </Button>
          </form>

          <p className="mt-5 text-center text-sm text-slate-600">
            {isLogin ? 'Chưa có tài khoản? ' : 'Đã có tài khoản? '}
            <Link to={isLogin ? '/register' : '/login'} state={location.state} className="font-semibold text-brand-600 hover:underline">
              {isLogin ? 'Đăng ký' : 'Đăng nhập'}
            </Link>
          </p>
        </section>
      </div>
    </div>
  )
}
