import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import CallHost from './components/call/CallHost'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import AuthPage from './pages/AuthPage'
import BoardPage from './pages/BoardPage'
import JoinPage from './pages/JoinPage'
import MeetingPage from './pages/MeetingPage'
import MyTasksPage from './pages/MyTasksPage'
import StatusPage from './pages/StatusPage'
import WorkspacePage from './pages/WorkspacePage'
import WorkspacesPage from './pages/WorkspacesPage'

// Trang phòng họp kéo theo thư viện LiveKit (~700KB) → chỉ tải khi có người thật sự mở phòng,
// các trang khác không bị nặng thêm (code splitting).
const RoomPage = lazy(() => import('./pages/RoomPage'))

// Bảng định tuyến: mỗi đường dẫn (URL) ứng với 1 trang.
// Các trang nằm trong <Layout> bắt buộc đăng nhập.
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/status" element={<StatusPage />} />
        <Route element={<Layout />}>
          <Route path="/" element={<WorkspacesPage />} />
          <Route path="/workspaces/:id" element={<WorkspacePage />} />
          <Route path="/boards/:id" element={<BoardPage />} />
          <Route path="/my-tasks" element={<MyTasksPage />} />
          <Route path="/meetings/:id" element={<MeetingPage />} />
          <Route path="/join/:code" element={<JoinPage />} />
          {/* GĐ6: phòng họp trực tuyến. Chưa đăng nhập → Layout chuyển sang /login rồi quay lại đúng link này */}
          <Route
            path="/room/:code"
            element={
              <Suspense fallback={<Spinner text="Đang mở phòng họp…" />}>
                <RoomPage />
              </Suspense>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* GĐ6 (phương án B): cuộc họp đang diễn ra sống ở đây, ngoài các trang → đổi trang không rớt cuộc họp */}
      <CallHost />
    </BrowserRouter>
  )
}
