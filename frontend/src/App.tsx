import { BrowserRouter, Route, Routes } from 'react-router-dom'
import StatusPage from './pages/StatusPage'

// Bảng định tuyến: mỗi đường dẫn (URL) ứng với 1 trang.
// Giai đoạn 2 sẽ thêm: /login, /workspaces/:id, /boards/:id, /meetings/:id ...
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<StatusPage />} />
      </Routes>
    </BrowserRouter>
  )
}
