import { useEffect } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { LayoutGrid, ListChecks, LogOut } from 'lucide-react'
import { resumePendingTracks } from '../lib/roomTrackUploader'
import { useAuth } from '../stores/auth'
import Avatar from './Avatar'
import Logo from './Logo'
import NotificationBell from './NotificationBell'
import ThemeToggle from './ThemeToggle'

/** Khung chung cho các trang cần đăng nhập: thanh trên cùng + nội dung trang. */
export default function Layout() {
  const { token, user, logout } = useAuth()
  const location = useLocation()
  const qc = useQueryClient()

  // GĐ6: lần trước đóng tab / rớt mạng khi đang họp Online Meeting → gửi nốt ghi âm còn dở
  // (ngay khi mở web, và mỗi khi có mạng lại)
  useEffect(() => {
    if (!token) return
    void resumePendingTracks()
    const onOnline = () => void resumePendingTracks()
    window.addEventListener('online', onOnline)
    return () => window.removeEventListener('online', onOnline)
  }, [token])

  // Chưa đăng nhập → chuyển về /login, nhớ trang đang muốn vào để quay lại sau
  if (!token || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  const navCls = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-1.5 text-sm font-medium transition ${
      isActive ? 'bg-brand-100 text-brand-700 shadow-sm' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
    }`

  // Mỗi trang "trồi nhẹ" lên khi mở. Phòng họp dùng chung một khóa để đi từ màn hình chờ vào phòng
  // (đổi địa chỉ /room/new → /room/<mã>) không bị dựng lại từ đầu.
  const pageKey = location.pathname.startsWith('/room/') ? 'room' : location.pathname

  return (
    // overflow-y-clip: lúc trang "trồi lên" (dịch 8px) phần dịch không làm trang dài thêm 8px
    // → không lóe thanh cuộn dọc mỗi lần chuyển trang
    <div className="flex min-h-dvh flex-col overflow-y-clip">
      <header className="glass-blur sticky top-0 z-30 border-b">
        <div className="flex h-14 items-center gap-1 px-3 sm:gap-2 sm:px-4">
          <Link to="/" className="mr-1 flex items-center gap-2 rounded-xl sm:mr-2" aria-label="MeetFlow — trang chủ">
            <Logo />
            <span className="text-gradient hidden text-[15px] font-bold tracking-tight sm:inline">MeetFlow</span>
          </Link>
          <nav className="flex gap-1" aria-label="Điều hướng chính">
            <NavLink to="/" end className={navCls}>
              <LayoutGrid className="size-4" aria-hidden="true" />
              Nhóm
            </NavLink>
            <NavLink to="/my-tasks" className={navCls}>
              <ListChecks className="size-4" aria-hidden="true" />
              <span className="max-[380px]:sr-only">Việc của tôi</span>
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-0.5 sm:gap-1">
            <ThemeToggle />
            <NotificationBell />
            <div className="ml-1 flex items-center gap-2">
              <Avatar user={user} />
              <span className="hidden max-w-40 truncate text-sm font-medium text-slate-700 md:inline">{user.full_name}</span>
            </div>
            <button
              className="ml-0.5 flex items-center gap-1.5 rounded-xl p-2 text-sm text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
              onClick={() => {
                logout()
                qc.clear() // xóa cache dữ liệu của người dùng cũ
              }}
              aria-label="Đăng xuất"
              title="Đăng xuất"
            >
              <LogOut className="size-4" aria-hidden="true" />
              <span className="hidden lg:inline">Đăng xuất</span>
            </button>
          </div>
        </div>
      </header>
      <main key={pageKey} className="flex min-h-0 flex-1 animate-page flex-col">
        <Outlet />
      </main>
    </div>
  )
}
