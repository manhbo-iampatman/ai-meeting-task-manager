# MeetFlow

**Đề tài KLTN:** Nghiên cứu và xây dựng hệ thống quản lý công việc nhóm tích hợp AI tự động tóm tắt cuộc họp và tạo đầu việc.

- Kế hoạch chi tiết: [docs/KE_HOACH_PHUONG_AN_B.md](docs/KE_HOACH_PHUONG_AN_B.md)
- Giải thích kiến thức Giai đoạn 0: [docs/GIAI_THICH_GIAI_DOAN_0.md](docs/GIAI_THICH_GIAI_DOAN_0.md)
- Giải thích kiến thức Giai đoạn 2: [docs/GIAI_THICH_GIAI_DOAN_2.md](docs/GIAI_THICH_GIAI_DOAN_2.md)
- Giải thích kiến thức Giai đoạn 3: [docs/GIAI_THICH_GIAI_DOAN_3.md](docs/GIAI_THICH_GIAI_DOAN_3.md)
- Giải thích kiến thức Giai đoạn 4: [docs/GIAI_THICH_GIAI_DOAN_4.md](docs/GIAI_THICH_GIAI_DOAN_4.md)

## Cấu trúc

```
backend/      FastAPI + SQLAlchemy + RQ worker + AI (faster-whisper, Gemini)
frontend/     React + Vite + TypeScript + TailwindCSS
experiments/  Dữ liệu và script đánh giá (WER, F1) cho chương thực nghiệm
docs/         Kế hoạch, tài liệu giải thích, sơ đồ
docker-compose.yml   PostgreSQL + Redis
```

## Yêu cầu

- Python 3.12, Node.js 20+, Git
- Docker Desktop (chạy PostgreSQL + Redis)
- (Khuyến nghị) GPU NVIDIA — không cần cài CUDA Toolkit, thư viện CUDA cài qua pip

## Cài đặt lần đầu

```bash
# 1. CSDL + hàng đợi
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
