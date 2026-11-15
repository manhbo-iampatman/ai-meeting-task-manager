# MeetFlow

**Đề tài KLTN:** Nghiên cứu và xây dựng hệ thống quản lý công việc nhóm tích hợp AI tự động tóm tắt cuộc họp và tạo đầu việc.

- Kế hoạch chi tiết: [docs/KE_HOACH_PHUONG_AN_B.md](docs/KE_HOACH_PHUONG_AN_B.md)
- Giải thích kiến thức Giai đoạn 0: [docs/GIAI_THICH_GIAI_DOAN_0.md](docs/GIAI_THICH_GIAI_DOAN_0.md)

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
copy .env.example .env                 # rồi điền GEMINI_API_KEY

# 3. Frontend
cd ../frontend
npm install
```

## Chạy hằng ngày (3 cửa sổ terminal)

| Terminal | Thư mục | Lệnh |
|---|---|---|
| 1. Backend API | `backend` | `.venv\Scripts\activate` rồi `uvicorn app.main:app --reload` |
| 2. Worker AI | `backend` | `.venv\Scripts\activate` rồi `python -m app.workers.worker` |
| 3. Frontend | `frontend` | `npm run dev` |

Mở http://localhost:5173 — trang trạng thái hệ thống cho biết thành phần nào đang chạy.
Tài liệu API (Swagger): http://localhost:8000/docs

## Kiểm tra nhanh

```bash
cd backend
.venv\Scripts\python -m pytest                         # test backend
.venv\Scripts\python scripts\test_whisper.py file.mp3  # chạy thử Whisper trên GPU
```
