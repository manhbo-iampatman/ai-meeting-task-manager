# GIẢI THÍCH GIAI ĐOẠN 0 — KHUNG DỰ ÁN

Tài liệu này giải thích **những gì đã dựng và vì sao**, để bạn tự trình bày trước hội đồng.
Đọc theo thứ tự từ trên xuống. Mỗi mục có phần **"Hội đồng hỏi thì trả lời"**.

---

## 1. Bức tranh tổng thể: hệ thống gồm những "mảnh" nào?

```
Trình duyệt ──► Frontend (React, cổng 5173)
                     │  gọi /api/...
                     ▼
                Backend (FastAPI, cổng 8000) ──► PostgreSQL (lưu dữ liệu, cổng 5433)
                     │
                     │ đẩy job
                     ▼
                Redis (hàng đợi, cổng 6379) ──► Worker AI (Whisper + LLM, dùng GPU)
```

Mỗi mảnh là một **chương trình chạy riêng**. Vì vậy khi phát triển bạn mở 3 terminal (backend, worker, frontend) cộng Docker (PostgreSQL + Redis).

---

## 2. Frontend — React + Vite + TypeScript + Tailwind

| Khái niệm | Giải thích ngắn |
|---|---|
| **React** | Thư viện xây giao diện bằng *component*: mỗi phần giao diện (nút, thẻ công việc, cột Kanban) là một hàm trả về HTML. Dữ liệu thay đổi thì React tự vẽ lại phần cần thiết. |
| **TypeScript** | JavaScript có *kiểu dữ liệu*. Viết sai tên trường (vd. `data.databse`) bị báo lỗi ngay khi code, không đợi chạy mới phát hiện. |
| **Vite** | Công cụ chạy dev server và đóng gói (build). Sửa code là trình duyệt cập nhật gần như tức thì. |
| **TailwindCSS** | Viết giao diện bằng class có sẵn (`rounded-xl`, `bg-white`, `px-5`) thay vì tự viết file CSS. |
| **TanStack Query** | Quản lý việc gọi API: tự cache, tự gọi lại, tự xử lý trạng thái đang tải / lỗi. |
| **Proxy `/api`** | Trong `vite.config.ts`: frontend gọi `/api/health`, Vite chuyển tiếp sang `localhost:8000/api/health`. Nhờ vậy frontend và backend chạy khác cổng mà vẫn gọi nhau được. |

**File đáng xem:** `frontend/src/pages/StatusPage.tsx`. Trang này gọi `/api/health` mỗi 5 giây và hiển thị trạng thái từng thành phần.

**Hội đồng hỏi "Tại sao chọn React?"** → Đây là thư viện phổ biến nhất, cộng đồng lớn, có sẵn thư viện kéo-thả (dnd-kit) và mô hình component dễ tái sử dụng: thẻ công việc dùng chung cho bảng Kanban và màn hình duyệt kết quả AI.

---

## 3. Backend — FastAPI

| Khái niệm | Giải thích ngắn |
|---|---|
| **API REST** | Frontend và backend "nói chuyện" qua HTTP: `GET /api/tasks` (lấy), `POST /api/tasks` (tạo), `PATCH` (sửa), `DELETE` (xóa). Dữ liệu dạng JSON. |
| **FastAPI** | Framework web Python. Hỗ trợ bất đồng bộ (async), tự kiểm tra dữ liệu vào bằng Pydantic, **tự sinh tài liệu API** ở `/docs`. |
| **Router** | Nhóm các API cùng chủ đề vào một file (`api/routes/health.py`, sau này có `tasks.py`, `meetings.py`). |
| **CORS** | Trình duyệt mặc định chặn web ở cổng 5173 gọi sang cổng 8000. Middleware CORS trong `main.py` cho phép điều đó. |
| **Cấu hình qua `.env`** | `core/config.py` đọc mật khẩu, API key từ file `.env`. Không ghi cứng vào code, và `.env` không bị đẩy lên Git. |

**Cấu trúc thư mục backend (tách lớp — layered architecture):**
```
api/routes/   Nhận request, trả response (mỏng, không chứa nghiệp vụ)
schemas/      Định nghĩa dữ liệu vào/ra (Pydantic)
services/     Nghiệp vụ (vd. "đẩy đầu việc lên bảng")
models/       Bảng CSDL (SQLAlchemy)
ai/           Phần AI tách riêng: stt/, llm/, postprocess/
workers/      Job chạy nền
core/         Cấu hình, kết nối CSDL, hàng đợi, bảo mật
```

**Hội đồng hỏi "Tại sao backend dùng Python mà không dùng Node.js?"** → Phần lõi của đề tài là AI: Whisper, LLM, các thư viện đánh giá như jiwer. Hệ sinh thái AI mạnh nhất là Python. Viết backend bằng Python thì backend và AI dùng chung code, chung ngôn ngữ.

---

## 4. PostgreSQL + SQLAlchemy

- **PostgreSQL:** hệ quản trị CSDL quan hệ. Hỗ trợ kiểu **JSONB**, rất hợp để lưu kết quả AI có cấu trúc linh hoạt như danh sách segments hay biên bản.
- **SQLAlchemy (ORM):** viết code Python thay cho SQL thuần. Ví dụ `db.query(Task).filter(...)` thay vì `SELECT * FROM tasks WHERE ...`. Code an toàn trước SQL injection và dễ đọc hơn.
- **Connection pool** (`core/database.py`): mở sẵn vài kết nối rồi dùng lại, không mở và đóng kết nối mới mỗi request.
- **Alembic** (Giai đoạn 2): quản lý *migration*. Mỗi lần đổi cấu trúc bảng thì tạo một "phiên bản" CSDL, giống Git nhưng dành cho CSDL.

---

## 5. Docker

- **Docker** chạy phần mềm trong *container*: một môi trường đóng gói sẵn, không cần cài PostgreSQL hay Redis trực tiếp vào Windows.
- `docker-compose.yml` mô tả cả 2 dịch vụ. Chỉ cần một lệnh `docker compose up -d` là cả hai cùng chạy.
- **Volume** (`pgdata`): dữ liệu được giữ lại kể cả khi tắt container.

**Vì sao backend và worker KHÔNG chạy trong Docker?** Worker cần GPU. Trên Windows, đưa GPU vào Docker phải qua WSL2 và cấu hình phức tạp, nên chạy trực tiếp trên máy đơn giản hơn.

---

## 6. Hàng đợi Redis + RQ + Worker — phần quan trọng nhất về kiến trúc

**Vấn đề:** chuyển 30 phút ghi âm thành văn bản mất vài phút. Nếu API xử lý trực tiếp:
- Trình duyệt phải chờ, dễ bị timeout.
- Trong lúc đó server bị chiếm tài nguyên.
- 3 người cùng upload thì GPU 4GB bị tràn bộ nhớ.

**Giải pháp — xử lý bất đồng bộ qua hàng đợi (Producer–Consumer):**
1. API nhận file, lưu lại, **đẩy một "job" vào hàng đợi Redis**, rồi trả lời ngay: "Đã nhận, đang xử lý".
2. **Worker** (chương trình riêng) lấy job ra và chạy Whisper rồi LLM.
3. Worker ghi % tiến độ vào `job.meta`. Frontend hiển thị thanh tiến độ (Giai đoạn 3 dùng WebSocket).
4. Worker xử lý **từng job một**, nên GPU không bao giờ bị quá tải.

**Chi tiết riêng cho Windows** (`workers/worker.py`): worker mặc định của RQ dùng `fork()`, một hàm Windows không có. Vì vậy mình dùng `SimpleWorker` kết hợp `TimerDeathPenalty`. Cách này còn có lợi: **mô hình Whisper chỉ nạp vào GPU một lần** rồi được giữ lại cho mọi job sau.

**Hội đồng hỏi "Tại sao không xử lý đồng bộ?"** → Trả lời theo 4 ý ở trên: timeout, chiếm tài nguyên, tràn VRAM, và trải nghiệm người dùng (có thanh tiến độ, có thể làm việc khác trong lúc chờ).

---

## 7. Phần AI — faster-whisper

| Khái niệm | Giải thích ngắn |
|---|---|
| **Whisper** | Mô hình nhận dạng giọng nói của OpenAI, mã nguồn mở, huấn luyện trên 680.000 giờ audio đa ngôn ngữ, có tiếng Việt. Kiến trúc Transformer *encoder–decoder*: audio → phổ Mel → encoder → decoder sinh ra chữ. |
| **faster-whisper** | Whisper chạy bằng thư viện CTranslate2, **nhanh hơn khoảng 4 lần**, tốn ít VRAM hơn, kết quả gần như không đổi. |
| **large-v3-turbo** | Bản rút gọn của large-v3: decoder giảm từ 32 xuống 4 lớp, nên nhanh hơn nhiều mà chất lượng gần bằng. |
| **int8 (lượng tử hóa)** | Lưu trọng số mô hình bằng số nguyên 8-bit thay vì số thực 16 hoặc 32-bit. VRAM giảm khoảng 2–4 lần, nhờ vậy vừa GPU 4GB. |
| **VAD** | *Voice Activity Detection*: bỏ các đoạn im lặng trước khi đưa vào Whisper. Xử lý nhanh hơn và Whisper ít "bịa chữ" khi không có tiếng nói. |
| **beam_size=5** | Khi sinh chữ, mô hình giữ 5 phương án tốt nhất song song rồi chọn câu có xác suất cao nhất (beam search). |

**Mẫu thiết kế Strategy** (`ai/stt/base.py`): mọi bộ STT đều có cùng hàm `transcribe()`. Muốn đổi từ Whisper trên máy sang Groq API chỉ cần sửa `STT_PROVIDER` trong `.env`. Chương thực nghiệm cũng dùng cơ chế này để so sánh các mô hình.

**Cài CUDA qua pip** (`ai/cuda_setup.py`): thay vì cài CUDA Toolkit nặng vài GB, chỉ cài 2 gói pip `nvidia-cublas-cu12` và `nvidia-cudnn-cu12`, rồi chỉ cho Windows biết thư mục chứa file `.dll`.

---

### Kết quả chạy thử thật trên RTX 3050 (15/11/2026)

File mẫu tiếng Anh 18,6 giây (giọng đọc máy của Windows), mô hình `large-v3-turbo` int8:

```
[ 0.00 →  3.58] Good morning everyone. Let's start the weekly meeting.
[ 4.55 →  7.27] NOM will finish the database design by next Friday.      ← "Nam"
[ 8.27 → 12.21] LAN, please prepare the slides for the client demo ...   ← "Lan"
[13.23 → 17.75] MIN will fix the login bug today. ...                    ← "Minh"
Thời gian xử lý: 2,67 giây → nhanh gấp 7 lần thời gian thực
```

**Nhận xét quan trọng cho báo cáo:** câu chữ nhận dạng gần như đúng hết, nhưng **tên riêng tiếng Việt bị nghe sai** ("Nam" thành "NOM", "Minh" thành "MIN"). Đây là bằng chứng thực tế cho thấy cần bước **ghép tên mờ (fuzzy matching) với danh sách thành viên** (Giai đoạn 4) và **màn hình duyệt để người dùng sửa**. Không thể tin tuyệt đối vào kết quả STT.

## 8. Kiểm thử

- `backend/tests/test_health.py`: kiểm tra `/api/health` luôn trả về 200 kể cả khi CSDL chưa chạy. Chạy bằng `pytest`.
- `backend/scripts/test_whisper.py`: chạy thử Whisper với một file audio, in kết quả kèm thời gian xử lý.

---

## Tự kiểm tra (trả lời được hết là nắm Giai đoạn 0)

1. Hệ thống có mấy thành phần chạy riêng? Mỗi thành phần chạy ở cổng nào?
2. Proxy `/api` trong Vite để làm gì?
3. CORS là gì? Vì sao cần?
4. Tại sao cần hàng đợi và worker?
5. Tại sao worker dùng `SimpleWorker` trên Windows?
6. int8 và VAD giúp gì?
7. Muốn đổi mô hình STT thì sửa ở đâu?
