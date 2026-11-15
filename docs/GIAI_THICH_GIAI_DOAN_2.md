# GIẢI THÍCH GIAI ĐOẠN 2 — PHÂN HỆ QUẢN LÝ CÔNG VIỆC

Giai đoạn này xây toàn bộ phần **quản lý** (F01–F08): đăng nhập, nhóm, bảng Kanban kéo-thả, realtime, thông báo.
Tài liệu đi theo thứ tự: **CSDL → Bảo mật → API → Kéo-thả → Realtime → Thông báo → Frontend → Kiểm thử**.

> Thử ngay: chạy `.venv\Scripts\python scripts\seed_demo.py` trong `backend`, rồi đăng nhập `nam@example.com` / `demo1234`.
> Muốn thử realtime: mở thêm một cửa sổ ẩn danh, đăng nhập `lan@example.com`, kéo thẻ ở một bên và xem bên kia tự cập nhật.

---

## 1. Cơ sở dữ liệu (8 bảng)

```
users ──< workspace_members >── workspaces ──< boards ──< columns ──< tasks ──< task_comments
  │                                                                     │
  └──────────────────────────< notifications          assignee_id ──────┘ (→ users)
```

| Bảng | Vai trò | Điểm đáng chú ý |
|---|---|---|
| `users` | Tài khoản | Chỉ lưu `password_hash`, **không bao giờ lưu mật khẩu gốc** |
| `workspaces` | Nhóm | `invite_code`: mã ngẫu nhiên dùng cho link mời |
| `workspace_members` | Ai thuộc nhóm nào | Bảng trung gian **nhiều–nhiều**; có `role` và `nicknames` (mảng PostgreSQL) |
| `boards` | Bảng Kanban | Mỗi nhóm có nhiều bảng |
| `columns` | Cột | `is_done`: cột "hoàn thành", việc nằm ở đây thì không bị nhắc hạn |
| `tasks` | Thẻ công việc | `position` là **số thực** (xem mục 4) |
| `task_comments` | Bình luận | |
| `notifications` | Thông báo | `payload` kiểu **JSONB**, lưu dữ liệu linh hoạt theo từng loại thông báo |

**Ràng buộc khóa ngoại (`ON DELETE`):**
- Xóa nhóm thì bảng, cột, thẻ, bình luận bị xóa theo (`CASCADE`). Một câu lệnh, CSDL tự lo phần còn lại.
- Xóa tài khoản người được giao thì thẻ vẫn còn, chỉ `assignee_id` thành rỗng (`SET NULL`).

**`nicknames` để làm gì?** Đây là chuẩn bị cho Giai đoạn 4. Khi AI nghe trong cuộc họp câu "anh Nam lo phần báo cáo", nó cần biết "anh Nam" là tài khoản nào. Kết quả test Whisper ở Giai đoạn 0 đã cho thấy tên riêng hay bị nghe sai, nên biệt danh càng quan trọng.

**Migration (Alembic):** file `backend/alembic/versions/..._khoi_tao_bang_quan_ly_cong_viec.py` do Alembic **tự sinh** bằng cách so sánh model Python với CSDL. Lệnh `alembic upgrade head` tạo bảng. Mỗi lần sửa model, chạy `alembic revision --autogenerate -m "..."` để tạo phiên bản mới.

---

## 2. Bảo mật: mật khẩu và đăng nhập

### 2.1. Băm mật khẩu bằng bcrypt (`core/security.py`)
```
"matkhau123"  ──bcrypt──►  "$2b$12$Kx8...(60 ký tự)"
```
- **Một chiều:** không thể dịch ngược chuỗi băm ra mật khẩu.
- **Có muối (salt) ngẫu nhiên:** hai người cùng đặt mật khẩu "123456" vẫn ra hai chuỗi băm khác nhau, nên không tra được bằng bảng tra sẵn (rainbow table).
- **Cố tình chạy chậm** (cost = 12, khoảng 0,2 giây mỗi lần): người dùng không cảm nhận được, nhưng kẻ tấn công thử hàng tỷ mật khẩu thì mất rất lâu.
- Khi đăng nhập: băm lại mật khẩu vừa nhập rồi so với chuỗi đã lưu (`bcrypt.checkpw`).

### 2.2. JWT (JSON Web Token)
```
eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiIxIiwiZXhwIjoxNz... . Xk2f9a...
       header                    payload (user id, hạn)        chữ ký
```
1. Đăng nhập đúng thì server tạo token chứa `sub` (id người dùng) và `exp` (hết hạn sau 7 ngày), rồi **ký** bằng `JWT_SECRET` (chuỗi bí mật trong `.env`).
2. Frontend lưu token, sau đó gửi kèm mọi request trong header `Authorization: Bearer <token>`. Việc gắn token được làm tự động trong `api/client.ts` (interceptor).
3. Server kiểm tra chữ ký. Ai sửa payload (ví dụ đổi id thành người khác) thì chữ ký không khớp và request bị từ chối.

**Ưu điểm:** server *không cần lưu phiên* (stateless), nên dễ mở rộng nhiều server.
**Nhược điểm cần thừa nhận nếu bị hỏi:** không thu hồi được token trước hạn. Hướng cải tiến là access token ngắn hạn (15 phút) cộng refresh token. Mình chọn một token 7 ngày cho đơn giản trong phạm vi khóa luận.

### 2.3. Các chi tiết bảo mật nhỏ (dễ ghi điểm)
- Đăng nhập sai email hay sai mật khẩu đều báo **cùng một câu** "Email hoặc mật khẩu không đúng", để kẻ gian không dò được email nào đã đăng ký.
- Người ngoài truy cập nhóm hoặc bảng của người khác nhận lỗi **404** thay vì 403, để không lộ việc nhóm đó có tồn tại.
- Chỉ giao việc được cho **thành viên trong nhóm** (`ensure_member_user`).
- WebSocket cũng kiểm tra token và quyền thành viên trước khi cho vào phòng.

---

## 3. Thiết kế API (REST)

| Nhóm | Ví dụ | Ý nghĩa |
|---|---|---|
| Xác thực | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` | |
| Nhóm | `GET/POST /api/workspaces`, `POST /api/workspaces/join` | Tham gia bằng mã mời |
| Thành viên | `POST /api/workspaces/{id}/members`, `PATCH .../members/{user_id}` | Thêm bằng email, sửa biệt danh |
| Bảng | `GET /api/boards/{id}` | Trả về **toàn bộ** cột và thẻ trong 1 lần gọi |
| Thẻ | `POST /api/boards/{id}/tasks`, `PATCH /api/tasks/{id}` | |
| Kéo-thả | `POST /api/tasks/{id}/move` `{column_id, index}` | |
| Bình luận | `POST /api/tasks/{id}/comments` | |
| Của tôi | `GET /api/me/tasks` | Việc của tôi ở mọi nhóm |
| Thông báo | `GET /api/notifications`, `POST .../read-all` | |
| Realtime | `WS /api/ws/boards/{id}?token=...` | |

Xem và **thử trực tiếp** mọi API tại http://localhost:8000/docs (Swagger do FastAPI tự sinh).

**Phân quyền:**
| Thao tác | Trưởng nhóm | Thành viên |
|---|---|---|
| Đổi tên / xóa nhóm, đổi mã mời, thêm hoặc xóa người | ✅ | ❌ |
| Sửa biệt danh | Của mọi người | Chỉ của mình |
| Bảng, cột, thẻ, bình luận | ✅ | ✅ |
| Rời nhóm | ❌ (phải xóa nhóm) | ✅ |

**Dependency Injection** (`api/deps.py`): các hàm như `get_current_user` và `get_board_for_member` được FastAPI tự gọi **trước** khi vào route. Mỗi route không phải lặp lại code kiểm tra token và quyền.

---

## 4. Kéo-thả: lưu thứ tự thẻ thế nào? (hội đồng rất hay hỏi)

**Cách ngây thơ:** lưu thứ tự là số nguyên 1, 2, 3, 4… Kéo thẻ lên đầu thì phải đánh số lại **toàn bộ cột**, có thể là hàng chục câu UPDATE.

**Cách mình dùng — Fractional indexing (chỉ số phân số):** lưu vị trí bằng **số thực**.
```
Trước:   A=1000   B=2000   C=3000
Kéo C vào giữa A và B → C = (1000 + 2000) / 2 = 1500
Sau:     A=1000   C=1500   B=2000          ← chỉ UPDATE đúng 1 dòng
```
- Đặt lên đầu: lấy vị trí thẻ đầu trừ 1000. Đặt xuống cuối: lấy thẻ cuối cộng 1000.
- Chèn liên tục vào cùng một chỗ thì khoảng cách nhỏ dần (1500, 1250, 1125…). Khi nhỏ hơn 0,000001, hệ thống **đánh số lại** cả cột thành 1000, 2000, 3000… (`_rebalance`). Việc này hiếm khi xảy ra.
- Test `test_many_moves_keep_order` kéo thả **60 lần liên tiếp vào cùng một chỗ** để chứng minh thứ tự luôn đúng.
- **Đã kiểm chứng trên trình duyệt:** kéo "Viết chương 2" vào giữa hai thẻ có vị trí 1000 và 2000, CSDL lưu đúng **1500**.

**Client chỉ gửi `{column_id, index}`** (cột đích và thứ tự mong muốn), còn server tự tính `position`. Logic nằm ở server nên client không thể gửi số sai.

### Optimistic update (cập nhật lạc quan) ở frontend
Khi thả thẻ, giao diện **đổi ngay** rồi mới gọi API ở nền. Nếu API lỗi thì tải lại dữ liệu thật. Người dùng không phải chờ mạng nên thao tác mượt. Code ở `KanbanBoard.tsx`, hàm `onDragEnd`.

**Thư viện dnd-kit:** `DndContext` bao cả bảng, `SortableContext` cho mỗi cột, `useSortable` cho mỗi thẻ và `useDroppable` cho vùng cột (để thả được vào cột trống). Phải kéo ít nhất 5px mới tính là kéo, nên bấm nhẹ vẫn mở được chi tiết thẻ.

---

## 5. Realtime bằng WebSocket

```
Lan kéo thẻ ──HTTP──► Backend lưu CSDL ──► broadcast tới "phòng" bảng 1
                                              │
                    ┌─────────────────────────┼──────────────────────┐
                    ▼                         ▼                      ▼
               Trình duyệt Nam          Trình duyệt Minh       Trình duyệt Lan
               nhận {"type":"board_updated"} → tự tải lại bảng
```
- **Polling** (cứ 2 giây hỏi server một lần): chậm, tốn request thừa.
- **WebSocket:** giữ một kết nối hai chiều, **server chủ động đẩy tin**, cập nhật gần như tức thì.
- Mỗi bảng là một "phòng" (`core/realtime.py`, lớp `ConnectionManager`).
- Tin nhắn chỉ báo "có thay đổi", client tự tải lại bảng qua API. Cách này đơn giản và luôn đúng dữ liệu, vì không phải đồng bộ từng trường.
- Mất mạng thì tự kết nối lại sau 2, 4, 8… tối đa 15 giây (exponential backoff). Góc trên bảng có chấm xanh "Trực tuyến".
- **Đã kiểm chứng:** tài khoản Lan thêm thẻ qua API, trang của Nam hiện thẻ mới mà **không cần tải lại**.

**Hai người cùng kéo một thẻ một lúc thì sao?** Ai gửi sau thì thắng (*last write wins*), sau đó mọi người nhận cập nhật và thấy cùng một trạng thái cuối. Với ứng dụng nhóm nhỏ, cách này chấp nhận được. Hướng nâng cao là khóa lạc quan (optimistic locking) bằng cột `version`.

**Giới hạn cần nói thật:** danh sách kết nối nằm trong RAM của **một** tiến trình backend. Chạy nhiều tiến trình thì cần **Redis Pub/Sub** để chia sẻ. Dự án đã có sẵn Redis nên nâng cấp dễ.

---

## 6. Thông báo (F08)

| Loại | Khi nào sinh |
|---|---|
| `task_assigned` 📌 | Ai đó giao việc cho bạn (tự giao cho mình thì không báo) |
| `task_due_soon` ⏰ | Việc của bạn đến hạn hôm nay hoặc ngày mai, chưa nằm ở cột hoàn thành |
| `task_overdue` ⚠️ | Việc của bạn đã quá hạn |

**Kỹ thuật "lười" (lazy generation):** không cần tiến trình chạy định kỳ (cron). Mỗi lần người dùng mở danh sách thông báo (chuông tự hỏi mỗi 30 giây), server mới kiểm tra hạn chót và sinh thông báo còn thiếu. Mỗi việc chỉ được báo **một lần** cho mỗi loại và mỗi hạn chót, có chống trùng.

---

## 7. Frontend

| Trang | Đường dẫn | Chức năng |
|---|---|---|
| Đăng nhập / Đăng ký | `/login`, `/register` | |
| Nhóm của bạn | `/` | Danh sách nhóm, tạo nhóm, dán link mời |
| Chi tiết nhóm | `/workspaces/:id` | Bảng, thành viên, biệt danh, link mời |
| Tham gia | `/join/:mã` | Mở link mời thì tự vào nhóm (chưa đăng nhập thì đăng nhập xong quay lại đúng link) |
| Bảng Kanban | `/boards/:id` | Kéo-thả, lọc, thêm cột, `?task=7` mở chi tiết thẻ |
| Việc của tôi | `/my-tasks` | Nhóm theo: Quá hạn / Hôm nay / Sắp tới / Không hạn |

**Các khái niệm React đáng nhớ:**
- **React Query** (`useQuery`, `useMutation`): tự cache dữ liệu. Sau khi sửa thì gọi `invalidateQueries`, dữ liệu liên quan tự tải lại.
- **Zustand + persist:** lưu token vào `localStorage`, tải lại trang vẫn còn đăng nhập.
- **Interceptor axios:** tự gắn token vào mọi request. Gặp lỗi 401 thì tự đăng xuất.
- **Layout + `<Outlet>`:** mọi trang cần đăng nhập nằm trong `Layout`. Chưa đăng nhập thì bị chuyển về `/login` và hệ thống nhớ trang đang muốn vào.
- **URL lưu trạng thái** (`?task=7`): bấm thông báo thì mở đúng thẻ, và có thể gửi link thẻ cho người khác.

**Bộ lọc:** lọc theo từ khóa, người làm ("Việc của tôi", "Chưa giao"), mức ưu tiên và hạn chót. Khi đang lọc thì **tắt kéo-thả**, vì thẻ bị ẩn sẽ làm sai thứ tự.

---

## 8. Kiểm thử

**14 test tự động** (`pytest`, chạy trên CSDL riêng `meetflow_test`, không đụng dữ liệu thật):

| Test | Kiểm tra |
|---|---|
| `test_register_login_me` | Đăng ký, đăng nhập (email không phân biệt hoa thường), lấy thông tin |
| `test_wrong_password_and_no_token` | Sai mật khẩu, thiếu token hay token giả đều nhận 401 |
| `test_password_is_hashed` | CSDL chỉ chứa chuỗi băm bcrypt |
| `test_non_member_cannot_access` | Người ngoài nhận 404 |
| `test_join_by_invite_code_and_permissions` | Tham gia bằng mã, phân quyền, biệt danh bỏ trùng, đổi mã thì mã cũ mất hiệu lực |
| `test_task_crud_move_and_order` | Thêm, sửa, xóa, kéo lên đầu, kéo sang cột khác, kéo xuống cuối |
| `test_many_moves_keep_order` | Kéo 60 lần vào cùng chỗ, kích hoạt rebalance, thứ tự vẫn đúng |
| `test_assign_notification_and_my_tasks` | Thông báo giao việc và sắp hạn, không trùng, "việc của tôi" |
| `test_overdue_and_cannot_assign_outsider` | Quá hạn; không giao được cho người ngoài nhóm |
| `test_comments_and_remove_member_unassigns` | Bình luận; xóa thành viên thì việc của họ thành "chưa giao" |
| `test_websocket_requires_membership` | Người ngoài bị từ chối WebSocket; thành viên nhận được sự kiện |

**Đã kiểm thử thủ công trên trình duyệt:** đăng nhập, xem bảng, kéo-thả (CSDL lưu đúng 1500), realtime từ tài khoản khác, bình luận, chuyển cột trong cửa sổ chi tiết, chuông thông báo, trang "Việc của tôi".

**Lỗi phát hiện nhờ kiểm thử:** email demo `@demo.local` bị thư viện từ chối vì `.local` là tên miền dành riêng. Mình đã sửa: đăng nhập không kiểm tra định dạng email, còn đăng ký vẫn kiểm tra.

---

## Tự kiểm tra (trả lời được hết là nắm Giai đoạn 2)

1. Vì sao không lưu mật khẩu gốc? bcrypt khác hàm băm thường (MD5, SHA) ở điểm nào?
2. JWT gồm mấy phần? Vì sao người dùng không tự sửa được id trong token?
3. Vì sao người ngoài nhận 404 chứ không phải 403?
4. Kéo thẻ vào giữa hai thẻ có vị trí 1000 và 2000 thì vị trí mới là bao nhiêu? Khi nào phải đánh số lại cả cột?
5. "Optimistic update" là gì? Nếu API lỗi thì sao?
6. WebSocket khác polling thế nào? Hai người cùng kéo một thẻ thì sao?
7. Thông báo "sắp đến hạn" được sinh ra khi nào, có cần cron không?
8. Bảng `workspace_members` là quan hệ gì? Cột `nicknames` để làm gì ở giai đoạn sau?
