import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { resumePendingTracks } from '../lib/roomTrackUploader'
import { useAuth } from '../stores/auth'
import Avatar from './Avatar'
import NotificationBell from './NotificationBell'

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
    `rounded-lg px-3 py-1.5 text-sm font-medium ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100'}`

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
        <div className="flex h-14 items-center gap-2 px-4">
          <Link to="/" className="mr-2 flex items-center gap-2 font-bold text-indigo-700">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-sm text-white">M</span>
            <span className="hidden sm:inline">MeetFlow</span>
          </Link>
          <nav className="flex gap-1">
            <NavLink to="/" end className={navCls}>
              Nhóm
            </NavLink>
            <NavLink to="/my-tasks" className={navCls}>
              Việc của tôi
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <NotificationBell />
            <div className="ml-1 flex items-center gap-2">
              <Avatar user={user} />
              <span className="hidden text-sm text-slate-700 md:inline">{user.full_name}</span>
            </div>
            <button
              className="ml-1 rounded-lg px-2 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
              onClick={() => {
                logout()
                qc.clear() // xóa cache dữ liệu của người dùng cũ
              }}
            >
              Đăng xuất
            </button>
          </div>
        </div>
      </header>
      <main className="flex min-h-0 flex-1 flex-col">
        <Outlet />
      </main>
    </div>
  )
}
