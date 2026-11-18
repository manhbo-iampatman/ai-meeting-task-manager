# MeetFlow

**Đề tài KLTN:** Nghiên cứu và xây dựng hệ thống quản lý công việc nhóm tích hợp AI tự động tóm tắt cuộc họp và tạo đầu việc.

- Kế hoạch chi tiết: [docs/KE_HOACH_PHUONG_AN_B.md](docs/KE_HOACH_PHUONG_AN_B.md)
- Khảo sát sản phẩm tương tự (Chương 1): [docs/KHAO_SAT_SAN_PHAM_TUONG_TU.md](docs/KHAO_SAT_SAN_PHAM_TUONG_TU.md)
- Giải thích kiến thức Giai đoạn 0: [docs/GIAI_THICH_GIAI_DOAN_0.md](docs/GIAI_THICH_GIAI_DOAN_0.md)
- Giải thích kiến thức Giai đoạn 2: [docs/GIAI_THICH_GIAI_DOAN_2.md](docs/GIAI_THICH_GIAI_DOAN_2.md)
- Giải thích kiến thức Giai đoạn 3: [docs/GIAI_THICH_GIAI_DOAN_3.md](docs/GIAI_THICH_GIAI_DOAN_3.md)
- Giải thích kiến thức Giai đoạn 4: [docs/GIAI_THICH_GIAI_DOAN_4.md](docs/GIAI_THICH_GIAI_DOAN_4.md)
- Giải thích kiến thức Giai đoạn 5: [docs/GIAI_THICH_GIAI_DOAN_5.md](docs/GIAI_THICH_GIAI_DOAN_5.md)
- Giải thích kiến thức Giai đoạn 6: [docs/GIAI_THICH_GIAI_DOAN_6.md](docs/GIAI_THICH_GIAI_DOAN_6.md)

## Cấu trúc

```
backend/      FastAPI + SQLAlchemy + RQ worker + AI (faster-whisper, Gemini)
frontend/     React + Vite + TypeScript + TailwindCSS
experiments/  Dữ liệu và script đánh giá (WER, F1) cho chương thực nghiệm
docs/         Kế hoạch, tài liệu giải thích, sơ đồ
scripts/      setup_lan.py — chuẩn bị chạy trong mạng LAN (IP, khóa LiveKit, chứng chỉ HTTPS)
docker-compose.yml   PostgreSQL + Redis + LiveKit (máy chủ phòng họp)
livekit.yaml         Cấu hình LiveKit
```

## Yêu cầu

- Python 3.12, Node.js 20+, Git
- Docker Desktop (chạy PostgreSQL + Redis + LiveKit)
- (Khuyến nghị) GPU NVIDIA — không cần cài CUDA Toolkit, thư viện CUDA cài qua pip

## Cài đặt lần đầu

```bash
# 1. CSDL + hàng đợi + máy chủ phòng họp
docker compose up -d

# 2. Backend
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-ai.txt     # thư viện AI, ~2GB
copy .env.example .env                 # rồi điền GEMINI_API_KEY, JWT_SECRET
alembic upgrade head                   # tạo bảng trong CSDL
python scripts\seed_demo.py            # (tuỳ chọn) dữ liệu demo — đăng nhập nam@example.com / demo1234

# 3. Frontend
cd ../frontend
npm install
```

## Chạy hằng ngày (3 cửa sổ terminal)

Không có Worker AI thì vẫn dùng được bảng công việc, nhưng cuộc họp tải lên sẽ đứng ở trạng thái "Đang chờ xử lý" và nút "Tóm tắt & tạo đầu việc" sẽ không ra kết quả.

| Terminal       | Thư mục    | Lệnh                                                         |
| -------------- | ---------- | ------------------------------------------------------------ |
| 1. Backend API | `backend`  | `.venv\Scripts\activate` rồi `uvicorn app.main:app --reload` |
| 2. Worker AI   | `backend`  | `.venv\Scripts\activate` rồi `python -m app.workers.worker`  |
| 3. Frontend    | `frontend` | `npm run dev`                                                |

Mở http://localhost:5173 để dùng ứng dụng. Trang http://localhost:5173/status cho biết thành phần nào đang chạy.
(Nhớ mở Docker Desktop trước. PostgreSQL của dự án chạy ở cổng **5433**.)
Tài liệu API (Swagger): http://localhost:8000/docs

## Tóm tắt bằng AI (Giai đoạn 4)

Mở một cuộc họp đã có bản ghi rồi bấm **"✨ Tóm tắt & tạo đầu việc"**. Cấu hình trong `backend/.env`:

| Biến           | Ý nghĩa                                                                              |
| -------------- | ------------------------------------------------------------------------------------ |
| `LLM_PROVIDER` | `gemini` (mặc định, cần Internet + `GEMINI_API_KEY`) hoặc `ollama` (chạy trên máy)   |
| `GEMINI_MODEL` | Mô hình Gemini chính, mặc định `gemini-3.5-flash` |
| `GEMINI_FALLBACK_MODEL` | Mô hình dự phòng, mặc định `gemini-3.5-flash-lite`. Mô hình chính quá tải / hết hạn mức (429, 503, 504, hết giờ) thì tự chuyển sang. Để trống = tắt |
| `LLM_TIMEOUT_SEC` | Chờ mỗi lần gọi Gemini tối đa bao nhiêu giây (mặc định 60) |
| `OLLAMA_MODEL` | Mô hình Ollama, mặc định `qwen2.5:3b` (cài Ollama rồi chạy `ollama pull qwen2.5:3b`) |

Đổi `.env` xong phải **khởi động lại Worker AI**.

## Duyệt & đẩy lên bảng (Giai đoạn 5)

- Trưởng nhóm hoặc người tải cuộc họp lên: mục **"Duyệt đầu việc"** trên trang cuộc họp → sửa, bỏ tick → **"⬆ Đẩy N việc lên bảng"**.
- Người chưa có tài khoản được giao **theo tên** ("Duy", "Su"). Tên đó hiện ở mục **"Tên chưa có người nhận"** trên trang nhóm; người đó vào nhóm bằng link mời rồi bấm **"Đây là tôi"**. Trưởng nhóm được báo và có thể hoàn tác.
- Lấy code mới xong: `alembic upgrade head` rồi khởi động lại API + Worker AI.

## Phòng họp trực tuyến "Online Meeting" (Giai đoạn 6)

Trang nhóm → **"📹 Online Meeting"** → màn hình chờ → **"Vào phòng"** (lúc này phòng mới được tạo; nhóm đang có phòng thì nút thành **"Tham gia phòng"**). Trong phòng: cam, mic, chia sẻ màn hình. Chủ phòng bấm **"● Bắt đầu ghi"** → mỗi người được ghi âm riêng → kết thúc phòng là có cuộc họp với **bản ghi có tên người nói**.

**Chỉ thử trên máy mình:** `docker compose up -d` (đã gồm LiveKit), `alembic upgrade head`, khởi động lại Backend API + Worker AI, rồi dùng `http://localhost:5173` như thường.

**Cho máy khác trong cùng Wi-Fi vào họp** (trình duyệt chỉ cho bật cam / mic trên `https`):

```bash
backend\.venv\Scripts\python scripts\setup_lan.py   # dò IP máy, tạo khóa LiveKit + chứng chỉ HTTPS tự ký (certs/)
docker compose up -d                                 # nạp lại LiveKit với IP mới
# khởi động lại Backend API, rồi:
cd frontend
npm run dev:lan                                      # https://<IP-máy>:5173
```

- Mọi người mở `https://<IP-máy>:5173`, lần đầu bấm **Nâng cao → Vẫn tiếp tục** (chứng chỉ tự ký).
- Gửi **link phòng** (nút "Chép link mời" trong phòng): người chưa ở trong nhóm đăng nhập / đăng ký xong là tự vào nhóm rồi vào phòng.
- Máy đổi mạng (đổi Wi-Fi, phát hotspot) → IP đổi → chạy lại `setup_lan.py` và `docker compose up -d`.
- Windows hỏi quyền tường lửa cho Node.js thì chọn cho phép. Vào được web mà không thấy hình / tiếng → mở cổng **7881 (TCP)** và **7882 (UDP)**.

| Biến (`backend/.env`) | Ý nghĩa |
| --- | --- |
| `LIVEKIT_URL` | Nơi backend gọi API quản lý phòng, mặc định `http://localhost:7880` |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Cặp khóa ký vé vào phòng — phải trùng với `.env` ở thư mục gốc (Docker đọc). `setup_lan.py` tự điền cả hai nơi |
| `ROOM_MAX_PARTICIPANTS` | Số người tối đa mỗi phòng, mặc định 6 |
| `ROOM_EMPTY_CLOSE_SEC` | Mọi người rời hết quá bấy nhiêu giây thì phòng tự đóng, mặc định 30 |
| `ROOM_UNJOINED_CLOSE_SEC` | Phòng vừa tạo mà không ai vào được (lỗi kết nối…): đóng sau bấy nhiêu giây, mặc định 60 |
| `ROOM_HOST_ABSENT_SEC` | Chủ phòng vắng quá bấy nhiêu giây (phòng còn người) thì nhượng quyền cho người vào sớm nhất, mặc định 60 |
| `ROOM_UPLOAD_WAIT_SEC` | Phòng kết thúc: chờ ghi âm của mọi người tối đa bấy nhiêu giây, mặc định 120 |

## Kiểm tra nhanh

```bash
cd backend
.venv\Scripts\python -m pytest                         # test backend
.venv\Scripts\python scripts\test_whisper.py file.mp3  # chạy thử Whisper trên GPU
```

## Dữ liệu thử nghiệm

```bash
backend\.venv\Scripts\pip install -r experiments\requirements.txt
backend\.venv\Scripts\python experiments\make_sample_meeting.py   # sinh cuộc họp tiếng Việt giả lập + đáp án chuẩn
backend\.venv\Scripts\python experiments\eval_extraction.py       # chấm bước trích xuất đầu việc (Precision / Recall / F1)
```
