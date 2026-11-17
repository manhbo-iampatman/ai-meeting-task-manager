import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import AuthPage from './pages/AuthPage'
import BoardPage from './pages/BoardPage'
import JoinPage from './pages/JoinPage'
import MeetingPage from './pages/MeetingPage'
import MyTasksPage from './pages/MyTasksPage'
import StatusPage from './pages/StatusPage'
import WorkspacePage from './pages/WorkspacePage'
import WorkspacesPage from './pages/WorkspacesPage'

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
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
