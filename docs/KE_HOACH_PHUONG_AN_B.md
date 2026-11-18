# KẾ HOẠCH THỰC HIỆN KHÓA LUẬN — PHƯƠNG ÁN B

**Tên đề tài:** Nghiên cứu và xây dựng hệ thống quản lý công việc nhóm tích hợp AI tự động tóm tắt cuộc họp và tạo đầu việc

**Tên dự án (gợi ý):** MeetFlow

**Máy phát triển:** i5-12500H · RAM 16GB · RTX 3050 Laptop 4GB VRAM · Windows 11

---

## 1. Mục tiêu

1. Xây dựng web quản lý công việc nhóm có bảng Kanban kéo-thả, cập nhật thời gian thực.
2. Xây dựng pipeline AI: **file ghi âm → văn bản → biên bản họp → danh sách đầu việc (Ai – Làm gì – Hạn chót)**.
3. Cho phép người dùng duyệt, sửa rồi **bấm 1 nút đẩy đầu việc lên bảng**.
4. **Phần nghiên cứu:** đánh giá, so sánh các mô hình chuyển giọng nói tiếng Việt và các LLM khi trích xuất đầu việc, có số liệu đo được.

---

## 2. Kiến trúc tổng thể

```
┌────────────────────┐   HTTP/REST + WebSocket   ┌──────────────────────────┐
│  Frontend (React)  │ ────────────────────────► │   Backend (FastAPI)      │
│  - Kanban kéo-thả  │ ◄──────────────────────── │  - Auth (JWT)            │
│  - Upload ghi âm   │                           │  - API nhóm/bảng/task    │
│  - Màn hình duyệt  │                           │  - API cuộc họp          │
└────────────────────┘                           └─────┬──────────┬─────────┘
                                                       │          │ đẩy job
                                              đọc/ghi  │          ▼
                                          ┌────────────▼──┐   ┌──────────┐
                                          │  PostgreSQL   │   │  Redis   │ (hàng đợi)
                                          └────────────▲──┘   └────┬─────┘
                                                       │           │ lấy job
                                                       │     ┌─────▼──────────────────────┐
                                                       └─────│  Worker AI (Python)         │
                                                             │  1. STT: faster-whisper      │
                                                             │  2. LLM: Gemini / Ollama     │
                                                             │  3. Hậu xử lý: map tên, ngày │
                                                             └──────────────────────────────┘
```

**Vì sao phải có Worker + Redis?** Chuyển 30 phút ghi âm thành văn bản mất vài phút. Nếu xử lý ngay trong request API thì trình duyệt bị treo hoặc timeout. Cách đúng là API chỉ nhận file, đưa "job" vào hàng đợi rồi trả về ngay. Worker xử lý dần và báo tiến độ qua WebSocket.
→ Đây là câu hội đồng hay hỏi: *"Tại sao không xử lý đồng bộ?"*

**Vì sao xử lý tuần tự?** GPU chỉ có 4GB, không giữ được cả Whisper lẫn LLM cùng lúc. Worker chạy 1 job một lúc, xong STT mới gọi LLM.

---

## 3. Công nghệ

| Lớp | Công nghệ | Lý do chọn (để trả lời hội đồng) |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript | Phổ biến, nhiều tài liệu, Vite build nhanh |
| UI | TailwindCSS + shadcn/ui | Giao diện đẹp nhanh, không phải tự viết CSS nhiều |
| Kéo-thả | dnd-kit | Thư viện kéo-thả hiện đại, hỗ trợ cảm ứng và bàn phím |
| Quản lý state/API | TanStack Query + Zustand | Tự cache, tự refetch dữ liệu từ server |
| Backend | FastAPI (Python 3.12) | Async, tự sinh tài liệu API (Swagger), cùng ngôn ngữ với phần AI |
| ORM / migration | SQLAlchemy 2 + Alembic | ORM chuẩn của Python, quản lý thay đổi CSDL theo phiên bản |
| CSDL | PostgreSQL 16 | Quan hệ, hỗ trợ JSONB để lưu kết quả AI |
| Hàng đợi | Redis + RQ | RQ đơn giản hơn Celery và chạy được trên Windows |
| Realtime | WebSocket (FastAPI) | Cập nhật bảng và tiến độ xử lý cho mọi thành viên |
| STT | faster-whisper (`large-v3-turbo`, int8, GPU) | Nhanh hơn Whisper gốc khoảng 4 lần, ít VRAM |
| STT (so sánh) | PhoWhisper (VinAI) | Mô hình riêng cho tiếng Việt, dùng ở chương thực nghiệm |
| LLM chính | Gemini API (gói miễn phí) | Tiếng Việt tốt, hỗ trợ trả JSON theo schema |
| LLM (so sánh) | Qwen2.5 3B qua Ollama | Chạy trên máy, không phụ thuộc Internet |
| Xử lý audio | ffmpeg | Chuẩn hóa mọi định dạng về WAV 16kHz mono |
| Hạ tầng dev | Docker Compose | Chạy PostgreSQL và Redis bằng 1 lệnh |

---

## 4. Chức năng chi tiết

### 4.1. Phân hệ quản lý (CRUD)
| Mã | Chức năng | Mô tả |
|---|---|---|
| F01 | Đăng ký / đăng nhập | Email + mật khẩu (bcrypt), JWT access + refresh token |
| F02 | Hồ sơ cá nhân | Tên hiển thị, ảnh đại diện, **biệt danh** (dùng để AI nhận ra tên trong cuộc họp) |
| F03 | Nhóm (workspace) | Tạo nhóm, mời thành viên bằng link hoặc email, vai trò Owner / Member |
| F04 | Bảng công việc | Mỗi nhóm có nhiều bảng, mặc định 4 cột Cần làm / Đang làm / Chờ duyệt / Hoàn thành |
| F05 | Thẻ công việc | Tiêu đề, mô tả, người làm, hạn chót, mức ưu tiên, nhãn, bình luận |
| F06 | Kéo-thả | Kéo thẻ giữa các cột và đổi thứ tự trong cột, cập nhật realtime |
| F07 | Lọc / tìm kiếm | Theo người làm, hạn chót, ưu tiên, "việc của tôi" |
| F08 | Thông báo | Khi được giao việc, khi sắp đến hạn hoặc quá hạn |

### 4.2. Phân hệ AI cuộc họp (trọng tâm)
| Mã | Chức năng | Mô tả |
|---|---|---|
| F09 | Tạo cuộc họp | Tên, ngày họp, người tham dự (chọn từ thành viên nhóm) |
| F10 | Upload | File ghi âm (mp3/m4a/wav/webm, tối đa ~100MB) **hoặc** dán / upload file text |
| F11 | Chuyển giọng nói | Có mốc thời gian từng đoạn, hiển thị % tiến độ realtime |
| F12 | Xem / sửa bản ghi | Người dùng sửa lỗi nhận dạng trước khi tóm tắt |
| F13 | Biên bản họp | Chủ đề, các ý chính, quyết định đã chốt, vấn đề còn mở |
| F14 | Trích xuất đầu việc | Danh sách {người làm, việc, hạn chót, ưu tiên, **trích dẫn câu gốc**} |
| F15 | Ghép tên | Ghép "Nam", "anh Nam", "Nam béo" với đúng tài khoản thành viên |
| F16 | Chuẩn hóa ngày | "thứ Sáu tuần sau" → 27/11/2026 (tính theo ngày họp) |
| F17 | Màn hình duyệt | Sửa / xóa / thêm đầu việc, chọn cột đích, **nút "Đẩy lên bảng"** |
| F18 | Lịch sử họp | Danh sách cuộc họp, xem lại biên bản, xem thẻ được tạo từ cuộc họp nào |
| F19 | Xuất biên bản | Xuất PDF / DOCX |

### 4.3. Mở rộng (chỉ làm khi phần lõi xong)
- E1. Ghi âm trực tiếp trên trình duyệt.
- E2. Hỏi đáp lịch sử cuộc họp (RAG).
- E3. Tách người nói bằng pyannote.
- E4. Dashboard thống kê khối lượng việc.

---

## 5. Thiết kế cơ sở dữ liệu (bản nháp)

```
users(id, email, password_hash, full_name, avatar_url, created_at)
workspaces(id, name, owner_id → users, created_at)
workspace_members(workspace_id, user_id, role, nicknames TEXT[])   -- biệt danh để AI ghép tên
boards(id, workspace_id, name)
columns(id, board_id, name, position)
tasks(id, column_id, title, description, assignee_id → users, due_date,
      priority, position, source_meeting_id → meetings NULL, created_by, created_at)
task_comments(id, task_id, user_id, content, created_at)

meetings(id, workspace_id, title, meeting_date, audio_url, status, created_by, created_at)
     -- status: uploaded → transcribing → summarizing → review → done | failed
meeting_participants(meeting_id, user_id)
transcripts(id, meeting_id, full_text, segments JSONB, stt_model, duration_sec, processing_sec)
meeting_summaries(id, meeting_id, summary JSONB, llm_model, created_at)
extracted_tasks(id, meeting_id, raw_assignee, assignee_id NULL, title, due_text, due_date NULL,
                priority, evidence_quote, status)   -- status: pending | accepted | rejected
notifications(id, user_id, type, payload JSONB, is_read, created_at)
```

Hai điểm thiết kế đáng nói khi bảo vệ:
- `extracted_tasks` tách riêng khỏi `tasks`: kết quả AI là **bản nháp**, chỉ thành công việc thật khi người dùng duyệt (thiết kế *human-in-the-loop*).
- `tasks.source_meeting_id` truy vết được mỗi thẻ sinh ra từ cuộc họp nào.

---

## 6. Pipeline AI chi tiết

```
[1] Upload ──► [2] ffmpeg chuẩn hóa ──► [3] STT ──► [4] LLM ──► [5] Hậu xử lý ──► [6] Màn hình duyệt ──► [7] Tạo task
                 WAV 16kHz mono          segments     JSON         map tên/ngày        người dùng sửa        ghi vào tasks
```

**Bước 3 – STT:** faster-whisper, `language="vi"`, bật `vad_filter` để bỏ đoạn im lặng (giảm "ảo giác" chữ khi im lặng), lưu segments `{start, end, text}`.

**Bước 4 – LLM:** một lần gọi với *structured output* (ép JSON theo schema):

```json
{
  "summary": { "topic": "...", "key_points": ["..."], "decisions": ["..."], "open_issues": ["..."] },
  "action_items": [
    { "assignee": "Nam", "task": "Hoàn thành báo cáo tuần",
      "due": "thứ Sáu tuần sau", "priority": "high",
      "evidence": "Nam lo phần báo cáo, hạn thứ Sáu tuần sau nhé" }
  ]
}
```

Prompt sẽ đưa vào: ngày họp, danh sách người tham dự kèm biệt danh, bản ghi. Yêu cầu: **không bịa**, việc nào không rõ người làm thì để `null`.

Bản ghi quá dài thì chia đoạn (chunking), tóm tắt từng đoạn rồi gộp lại (map-reduce).

**Bước 5 – Hậu xử lý (code Python, không dùng AI):**
- Ghép tên: so khớp không dấu và mờ (fuzzy, thư viện `rapidfuzz`) với tên và biệt danh thành viên.
- Ngày: luật tiếng Việt cho "hôm nay / mai / thứ X tuần này / tuần sau / cuối tháng" + `dateparser`.

**Thiết kế mở rộng:** interface `STTProvider` (local / groq) và `LLMProvider` (gemini / ollama), chọn qua biến môi trường. Đổi mô hình không phải sửa code; chương thực nghiệm cũng dùng chính cơ chế này.

---

## 7. Thiết kế thực nghiệm (chương 4 báo cáo)

**Dữ liệu:**
- 10–20 đoạn họp tiếng Việt, mỗi đoạn 3–15 phút. Tự ghi với nhóm bạn đóng vai họp (có nói chen, tiếng ồn), cộng thêm 1 phần dữ liệu công khai (vd. VIVOS, Common Voice tiếng Việt) để kiểm STT.
- Tự gõ **bản ghi chuẩn** và **danh sách đầu việc chuẩn** cho từng đoạn (ground truth).

**Thí nghiệm 1 – STT:**
| Mô hình | Đo |
|---|---|
| whisper small / medium / large-v3-turbo (faster-whisper) | WER (tỉ lệ lỗi từ), thời gian xử lý / 1 phút audio, VRAM |
| PhoWhisper small / medium | như trên |
Công cụ: thư viện `jiwer`.

**Thí nghiệm 2 – Trích xuất đầu việc:**
| Mô hình | Đo |
|---|---|
| Gemini (Flash) | Precision / Recall / F1 đầu việc, độ đúng người làm, độ đúng hạn chót |
| Qwen2.5 3B (Ollama) | như trên |
| (tuỳ chọn) có / không có danh sách biệt danh trong prompt | ảnh hưởng tới độ đúng người làm |

**Thí nghiệm 3 – End-to-end:** chạy trên bản ghi do STT sinh ra so với bản ghi chuẩn, để thấy lỗi STT lan sang bước trích xuất thế nào.

---

## 8. Lộ trình 14 tuần

> Dự kiến bắt đầu 16/11/2026. Mỗi giai đoạn có mục **"Kiến thức cần nắm"**: mình sẽ giải thích kỹ phần này để bạn tự trả lời được trước hội đồng.

### Giai đoạn 0 – Chuẩn bị (Tuần 1: 16/11 – 22/11)
- [x] Cài Docker Desktop, lấy Gemini API key
- [x] Khởi tạo repo Git, cấu trúc thư mục, Docker Compose (PostgreSQL + Redis)
- [x] Khung FastAPI + khung React chạy được "Hello"
- [x] Chạy thử faster-whisper trên GPU với 1 file mẫu
- **Kiến thức cần nắm:** kiến trúc client–server, REST API, Docker là gì, vì sao chọn FastAPI

### Giai đoạn 1 – Phân tích thiết kế (Tuần 2: 23/11 – 29/11)
- [ ] Khảo sát sản phẩm tương tự: Trello, Jira, Notion AI, Otter.ai, Fireflies.ai
- [ ] Vẽ use case, sơ đồ hoạt động của pipeline AI, ERD, sơ đồ tuần tự "upload → task"
- [ ] Wireframe các màn hình chính
- **Kiến thức cần nắm:** UML, chuẩn hóa CSDL, vì sao thiết kế human-in-the-loop

### Giai đoạn 2 – Phân hệ quản lý (Tuần 3–5: 30/11 – 20/12)
- [x] Auth JWT, user, workspace, mời thành viên (F01–F03)
- [x] Board, column, task, comment, API + giao diện (F04–F05)
- [x] Kéo-thả + lưu thứ tự + WebSocket realtime (F06)
- [x] Lọc, tìm kiếm, thông báo (F07–F08)
- **Kiến thức cần nắm:** JWT hoạt động thế nào, băm mật khẩu bcrypt, WebSocket so với polling, cách lưu thứ tự thẻ khi kéo-thả

### Giai đoạn 3 – STT (Tuần 6–7: 21/12 – 03/01)
- [x] API upload + lưu file + tạo meeting (F09–F10)
- [x] Redis + RQ worker, cập nhật trạng thái, đẩy % tiến độ qua WebSocket
- [x] ffmpeg + faster-whisper, lưu segments (F11)
- [x] Giao diện xem/sửa bản ghi, phát audio theo đoạn (F12)
- **Kiến thức cần nắm:** Whisper hoạt động thế nào (encoder–decoder Transformer, log-Mel spectrogram), VAD, lượng tử hóa int8, hàng đợi bất đồng bộ

### Giai đoạn 4 – LLM tóm tắt & trích xuất (Tuần 8–9: 04/01 – 17/01)
- [x] Thiết kế prompt + JSON schema, gọi Gemini (F13–F14)
- [x] Chunking cho bản ghi dài
- [x] Ghép tên (rapidfuzz) và chuẩn hóa ngày tiếng Việt (F15–F16)
- [x] Provider Ollama để so sánh
- **Kiến thức cần nắm:** LLM là gì, prompt engineering, structured output, hallucination và cách giảm (trích dẫn câu gốc, con người duyệt)

### Giai đoạn 5 – Duyệt & đẩy lên bảng (Tuần 10: 18/01 – 24/01) — làm xong sớm 18/11/2026
- [x] Màn hình duyệt, nút "Đẩy lên bảng" tạo nhiều task trong 1 transaction (F17)
- [x] Truy vết thẻ ↔ cuộc họp + câu gốc (F18, phần truy vết)
- [x] Giao việc theo tên (F20) + tự nhận tên, trưởng nhóm hoàn tác (F21) — xem mục 15–16
- [ ] Lịch sử họp đầy đủ, xuất PDF/DOCX (F19) — để lượt sau

### Giai đoạn 6 – Phòng họp trực tuyến "Online Meeting" (thêm 18/11/2026, ước 2–3 tuần) — xem mục 17
- [x] LiveKit (Docker) + HTTPS tự ký, phòng họp có cam / mic / chia sẻ màn hình chạy trong LAN
- [x] Ghi âm riêng từng người, gửi dần lên máy chủ
- [x] Ghép bản ghi có tên người nói, lọc tiếng vọng, đưa vào pipeline GĐ4
- [x] Dùng tên người nói để giao việc "để em làm" cho đúng người
- [ ] Thử với hai thiết bị thật trong cùng Wi-Fi (mic thật, cam, chia sẻ màn hình) — xem mục 10 của `GIAI_THICH_GIAI_DOAN_6.md`
- **Kiến thức cần nắm:** WebRTC (SFU, ICE/STUN/TURN), vì sao trình duyệt bắt buộc HTTPS mới cho dùng cam / mic, JWT cấp quyền vào phòng, vì sao ghi riêng từng người thay cho tách người nói bằng AI (diarization)

### Giai đoạn 7 – Thực nghiệm (Tuần 11: 25/01 – 31/01)
- [ ] Thu, gán nhãn dữ liệu, viết script đánh giá, chạy 3 thí nghiệm, vẽ biểu đồ
- [ ] Thí nghiệm 4 (mới): độ đúng người làm khi bản ghi **có / không có nhãn người nói**
- **Kiến thức cần nắm:** WER, Precision / Recall / F1, cách đọc và giải thích kết quả

### Giai đoạn 8 – Hoàn thiện (Tuần 12: 01/02 – 07/02)
- [ ] Kiểm thử (pytest cho backend, kiểm thử thủ công theo kịch bản), sửa lỗi
- [ ] Seed dữ liệu demo, quay video demo dự phòng
- [ ] (Tuỳ chọn) deploy: Vercel + Render + Neon, STT qua Groq

### Giai đoạn 9 – Báo cáo & bảo vệ (Tuần 13–14: 08/02 – 21/02)
- [ ] Viết báo cáo, làm slide, luyện bộ câu hỏi bảo vệ (mục 10)

> Tết Nguyên đán 2027 rơi vào khoảng 06/02/2027, nên giai đoạn 8–9 có thể bị lùi. Nên làm nhanh giai đoạn 2–5 để có dư thời gian.

---

## 9. Cấu trúc thư mục dự kiến

```
D:\KLTN\DT2\
├── docs/                    # kế hoạch, sơ đồ, báo cáo
├── docker-compose.yml       # PostgreSQL + Redis
├── backend/
│   ├── app/
│   │   ├── api/             # route: auth, workspaces, boards, tasks, meetings
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic (dữ liệu vào/ra)
│   │   ├── services/        # nghiệp vụ
│   │   ├── ai/
│   │   │   ├── stt/         # faster_whisper_provider.py, groq_provider.py
│   │   │   ├── llm/         # gemini_provider.py, ollama_provider.py, prompts.py
│   │   │   └── postprocess/ # name_matching.py, vi_date_parser.py
│   │   ├── workers/         # job xử lý cuộc họp (RQ)
│   │   └── core/            # config, security, database
│   ├── alembic/             # migration
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/           # Login, Workspace, Board, Meetings, MeetingReview
│       ├── components/      # KanbanBoard, TaskCard, UploadDialog, ...
│       ├── api/             # gọi backend
│       └── stores/
└── experiments/             # dữ liệu + script đánh giá WER, F1 + notebook biểu đồ
```

---

## 10. Rủi ro và cách xử lý

| Rủi ro | Cách xử lý |
|---|---|
| STT sai nhiều với ghi âm ồn | VAD, cho phép sửa bản ghi, upload text thay thế, báo cáo WER một cách trung thực |
| AI gán sai người làm | Danh sách biệt danh, fuzzy matching, bắt buộc duyệt trước khi tạo task |
| AI bịa đầu việc | Bắt trích dẫn câu gốc (`evidence`), prompt cấm suy diễn, con người duyệt |
| Gemini hết hạn mức miễn phí | Chuyển sang Ollama hoặc Groq qua biến môi trường |
| GPU 4GB thiếu VRAM | int8, xử lý tuần tự, dự phòng chạy CPU hoặc Groq |
| Mất mạng khi bảo vệ | Ollama + Whisper chạy offline, cộng video demo dự phòng |
| Trễ tiến độ | Làm phần lõi F01–F17 trước; mở rộng E1–E4 chỉ khi còn thời gian |

---

## 11. Câu hỏi hội đồng hay hỏi (sẽ chuẩn bị đáp án)

1. Tại sao chọn Whisper mà không dùng Google Speech-to-Text?
2. Phần "nghiên cứu" của em ở đâu, hay chỉ gọi API?
3. Nếu AI gán sai người hoặc bịa việc thì sao?
4. Sao không xử lý đồng bộ mà phải có hàng đợi?
5. Dữ liệu cuộc họp có bảo mật không, có gửi ra bên ngoài không? (→ có chế độ chạy offline hoàn toàn)
6. WER bao nhiêu thì chấp nhận được? Kết quả của em so với công bố của PhoWhisper thế nào?
7. Hệ thống xử lý được cuộc họp dài bao lâu?
8. Realtime hoạt động thế nào khi 2 người cùng kéo một thẻ?

---

## 12. Báo cáo khóa luận (khung)

- **Chương 1. Tổng quan:** bối cảnh, bài toán, mục tiêu, phạm vi, khảo sát sản phẩm tương tự
- **Chương 2. Cơ sở lý thuyết:** Kanban; nhận dạng giọng nói và Whisper; LLM, prompt engineering, structured output; kiến trúc hàng đợi bất đồng bộ; WebSocket
- **Chương 3. Phân tích và thiết kế:** use case, ERD, kiến trúc, pipeline AI, giao diện
- **Chương 4. Cài đặt và thực nghiệm:** môi trường, kết quả thí nghiệm, đánh giá
- **Kết luận và hướng phát triển**

---

## 13. Quyết định bổ sung (16/11/2026)

Sau khi trao đổi về luồng sử dụng thực tế, chốt thêm các điểm sau (làm ở Giai đoạn 3–5):

**Giảm rào cản ban đầu**: chỉ người tổ chức cuộc họp bắt buộc có tài khoản.
| Mã | Chức năng | Mô tả |
|---|---|---|
| F20 | Giao việc theo tên | Thêm cột `tasks.assignee_name`: AI nghe "Duy" mà chưa khớp tài khoản nào → vẫn tạo thẻ, gán tên dạng chữ |
| F21 | Gộp tên vào tài khoản | ~~Khi Duy đăng ký + vào nhóm → chọn gộp các thẻ tên "Duy" vào tài khoản của Duy~~ → **đổi thành "tự nhận tên"**, xem mục 15 |
| F22 | Sao chép tin nhắn kết quả | Sau "Đẩy lên bảng": tạo sẵn tin nhắn (ai – việc – hạn + link mời) để dán vào Zalo / Messenger |

**Thông báo qua email** (chỉ gửi cho người ĐÃ có tài khoản — hệ thống không tự đoán email):
| Mã | Chức năng | Người nhận |
|---|---|---|
| F23 | Email "bạn được giao việc" từ cuộc họp | Người được giao (mỗi người chỉ thấy việc của mình) |
| F24 | Thông báo **"Duy đã hoàn thành …"** khi thẻ vào cột hoàn thành | Người giao việc (chuông + email) — *khép vòng theo dõi tiến độ* |
| F25 | **Email tổng kết cuối ngày** | Trưởng nhóm: số việc xong / đang làm / quá hạn, ai đang trễ |

Gửi email qua Gmail SMTP (miễn phí). Không gửi email cho mọi thay đổi nhỏ để tránh spam.

**Mở rộng (nếu còn thời gian)**: E5 — *Voice note giao việc nhanh*: bấm micro nói 1 câu → thẻ lên bảng. Dùng lại nguyên pipeline Whisper + LLM.

**Câu trả lời khi hội đồng hỏi "sao không dán vào ChatGPT?"**: công cụ tóm tắt chỉ dừng ở biên bản; hệ thống biến biên bản thành công việc **có người chịu trách nhiệm, có hạn, được nhắc và theo dõi tiến độ** — đúng vấn đề "họp xong thì quên việc".

---

## 14. Quyết định bổ sung cho Giai đoạn 4 (17/11/2026)

| Tình huống | Quyết định |
|---|---|
| Người nói **tự nhận việc** ("để em làm", "phần này anh lo") mà bản ghi không cho biết ai nói | **Để trống người làm**, giữ đại từ gốc, đánh dấu "người nói tự nhận"; người dùng chọn ở màn hình duyệt (GĐ5). Không mặc định gán cho người tạo cuộc họp |
| **Một việc giao nhiều người** ("Lan và Minh làm slide") | **Tách mỗi người một đầu việc** |
| **Hạn chót mơ hồ** | Ước lượng theo quy ước cố định và gắn cờ "ước lượng": cuối tuần = **Chủ nhật**, đầu tuần = thứ Hai, cuối tháng = ngày cuối tháng |
| **Ollama** (máy chưa cài) | Viết provider + test giả lập ở GĐ4; chạy thật và so sánh với Gemini ở giai đoạn Thực nghiệm (GĐ7) |
| **Gemini quá tải** (503/504, chờ 3–4 phút rồi lỗi) | Mô hình chính `gemini-3.5-flash`, **tự chuyển sang `gemini-3.5-flash-lite`** khi gặp 429/503/504/hết giờ. Thời gian chờ mỗi lần gọi giảm từ 180 xuống **60 giây** |
| Đã chuyển sang dự phòng mà bản ghi còn nhiều đoạn | Dùng luôn mô hình dự phòng cho các đoạn còn lại; lần tóm tắt sau lại thử mô hình chính trước |
| Báo cho người dùng khi dùng mô hình dự phòng | Có: gợi ý sau 20 giây chờ, thông báo lúc chuyển, nhãn "mô hình dự phòng" trên biên bản |

Chi tiết và lý do: `docs/GIAI_THICH_GIAI_DOAN_4.md`.

---

## 15. F21 đổi thành "tự nhận tên" (17/11/2026)

**Vấn đề:** trong họp người ta hay gọi nhau bằng biệt danh, tên thân mật, tên giả ("Su", "anh Hai"...). Tên đăng ký tài khoản là "Trần Thị Lan" thì máy không có cách nào biết "Su" là Lan, nên kế hoạch cũ "khi người đó đăng ký thì gộp theo tên" sẽ hỏng.

**Ý tưởng (do người làm khóa luận đề xuất):** những tên AI nghe được mà chưa khớp tài khoản nào được hiện thành danh sách **"tên chưa có người nhận"**. Người vào nhóm (qua link mời) thấy danh sách đó, **bấm vào tên của mình** để nhận các việc mang tên ấy, rồi nhận thông báo về việc của mình.

| Điểm | Quyết định |
|---|---|
| Hướng làm F21 | **Người dùng tự nhận tên của mình**, thay cho việc hệ thống tự gộp theo tên |
| Bấm nhận tên | **Có hiệu lực ngay**; trưởng nhóm nhận thông báo và có thể **hoàn tác** nếu nhận nhầm / nhận bậy |
| Làm trong giai đoạn nào | **Ngay trong GĐ5**, cùng màn hình duyệt (chốt 17/11/2026) |

**Đề xuất đi kèm (đã chốt cả 4 điểm đầu, 17/11/2026):**
- Nhận theo **tên** chứ không theo từng việc: nhận "Su" = nhận mọi việc mang tên "Su". Một người nhận được nhiều tên.
- Tên vừa nhận được **lưu thành biệt danh** của người đó trong nhóm → các cuộc họp sau AI tự ghép đúng (hệ thống "học" qua biệt danh).
- **Mọi thành viên** đều xem được danh sách, không chỉ người mới vào (thành viên cũ cũng có thể bị gọi bằng biệt danh lạ). *(18/11: sửa lại — người đã nhận tên thì không thấy danh sách nữa, xem mục 16.)*
- Việc mà người nói tự nhận bằng đại từ ("để em làm") **không** đưa vào danh sách nhận tên; trưởng nhóm chọn người ở màn hình duyệt.
- Trưởng nhóm vẫn có thể **gán thẳng** tên cho một thành viên lúc duyệt.
- Hệ thống có thể **gợi ý** "Bạn có phải là Lan trong cuộc họp 17/11?" khi tên tài khoản gần giống, nhưng **không bao giờ tự nhận thay**.

---

## 16. Quyết định cho Giai đoạn 5 (17/11/2026)

| Tình huống | Quyết định |
|---|---|
| Ai được duyệt + đẩy lên bảng | **Trưởng nhóm + người tải cuộc họp lên**. Thành viên khác chỉ xem |
| Việc chưa có người làm (đại từ tự nhận, "cả nhóm") | **Cho đẩy**, thẻ để trống người làm |
| Hạn "ước lượng" / không thấy câu gốc | **Chỉ tô màu cảnh báo**, không chặn |
| Sau khi đẩy có tóm tắt lại được không | **Có, và đẩy thêm được**. Việc đã đẩy được giữ lại; việc mới trùng thì gắn "đã có trên bảng" + **bỏ tick sẵn** |
| Việc bị bỏ tick lúc đẩy | Đánh dấu **"đã bỏ"**, vẫn xem được, tick lại rồi đẩy lần sau |
| Bảng đích | **Chọn bảng lúc duyệt** (mặc định bảng đầu tiên), thẻ vào **cột đầu tiên** |
| F20 với thẻ tạo tay | **Có**: chọn thành viên hoặc gõ tên |
| Gộp tên chờ nhận | Bỏ xưng hô + không phân biệt hoa/thường, **giữ dấu** ("Năm" ≠ "Nam") |
| Thông báo khi nhận tên | **Một thông báo tổng** cho người nhận; trưởng nhóm 1 thông báo kèm nút Hoàn tác |
| F18 / F19 | Làm **phần truy vết F18**; **F19 (xuất PDF/Word) để sau** |
| *(18/11, sau khi dùng thử)* Ai thấy danh sách "Tên chưa có người nhận" | Thành viên **chưa nhận tên** nào. Đã nhận một tên (chưa bị hoàn tác) thì **ẩn hẳn danh sách**; bị hoàn tác thì thấy lại. Thay cho quyết định "mọi thành viên đều thấy" ở mục 15 |
| *(18/11, sau khi dùng thử)* Ai được kéo thả / sửa / xóa thẻ | **Người làm + người tạo thẻ + trưởng nhóm**. Thành viên khác chỉ xem và bình luận. Thẻ chưa có người làm / giao theo tên chữ: người tạo + trưởng nhóm. Thay cho thiết kế "ai cũng sửa được" của GĐ2 |

Chi tiết và lý do: `docs/GIAI_THICH_GIAI_DOAN_5.md`.

---

## 17. Phòng họp trực tuyến "Online Meeting" — Giai đoạn 6 (18/11/2026)

**Ý tưởng (do người làm khóa luận đề xuất):** họp ngay trong ứng dụng. Mỗi người vào phòng bằng tài khoản của mình và có **một luồng âm thanh riêng**, nên hệ thống biết chắc *ai nói câu nào* — đúng điểm yếu lớn nhất của bản ghi từ file ghi âm (GĐ4 phải để trống người làm khi gặp "để em làm").

**Vị trí trong hệ thống:** đây là **nguồn cuộc họp thứ ba**, bên cạnh tải file và ghi âm trực tiếp — không thay thế hai nguồn kia (họp ngồi chung một phòng, hoặc đã quen Zoom / Meet thì vẫn tải file lên). Bảng Kanban, pipeline AI, màn hình duyệt, F20/F21 giữ nguyên.

| Điểm | Quyết định |
|---|---|
| Triển khai bản đầu | **Demo trong mạng LAN.** LiveKit (máy chủ phòng họp, mã nguồn mở) chạy bằng Docker trên laptop; web, API và kết nối phòng họp đi qua **một địa chỉ** `https://<IP-laptop>:5173` |
| HTTPS | Bắt buộc (trình duyệt chỉ cho dùng cam / mic trên https hoặc localhost). Dùng **chứng chỉ tự ký bằng OpenSSL**; mỗi máy lần đầu bấm "Nâng cao → Vẫn tiếp tục". Không dùng mkcert vì phải cài CA gốc vào Windows |
| Ai được vào phòng | **Bắt buộc có tài khoản** (không có khách gõ tên). Riêng với phòng họp, điều này thay cho quyết định 16/11 "chỉ người tổ chức cần tài khoản" |
| Người chưa ở trong nhóm mở link phòng | Đăng nhập / đăng ký xong **tự vào nhóm rồi vào phòng**, giống Google Meet |
| Link phòng | **Mỗi buổi họp một link mới**; phòng kết thúc thì link hết dùng được |
| Ai được mở phòng | **Mọi thành viên.** Người mở là **chủ phòng**: bấm "Bắt đầu ghi", "Kết thúc cho mọi người", và được duyệt đầu việc như "người tải cuộc họp lên" |
| Nhóm đang có phòng mở | **Mỗi nhóm chỉ một phòng mở.** Thành viên vào sau chỉ thấy nút **"Tham gia phòng"**, bấm là vào thẳng; không tạo được phòng thứ hai |
| Ai điều khiển phòng (ghi âm, kết thúc) | **Chủ phòng + trưởng nhóm.** Danh sách người tham gia hiện nhãn "Chủ phòng" / "Trưởng nhóm" để ai cũng hiểu vì sao người đó có nút |
| Chủ phòng bấm "Rời phòng" *(18/11, sau khi thử 2 máy)* | **Hỏi lại như Google Meet**: "Chỉ mình tôi rời" → quyền chủ phòng chuyển NGAY cho người vào sớm nhất còn lại; hoặc "Kết thúc cho mọi người". Chủ phòng là người cuối cùng → rời là kết thúc buổi họp |
| Chủ phòng mất mạng / mất điện *(18/11)* | Phòng và ghi âm vẫn tiếp tục. Vắng **quá 1 phút** → nhượng quyền cho người vào sớm nhất còn lại (vào lại kịp thì vẫn là chủ phòng). Chủ phòng cũ vào lại sau đó là người tham gia thường — trừ khi là trưởng nhóm thì vẫn điều khiển được |
| Ai duyệt đầu việc sau họp | **Chủ phòng lúc kết thúc** + trưởng nhóm |
| Trước khi vào phòng | **Màn hình chờ** (xem trước hình, chọn mic / cam), mặc định **mic bật, cam tắt** |
| Tên người nói trong bản ghi | **Họ tên đầy đủ** ("Nguyễn Văn Nam: …") — không nhầm khi trùng tên |
| Phòng kết thúc khi nào | Chủ phòng bấm kết thúc, hoặc **tự đóng 30 giây sau khi mọi người rời hết** *(18/11, sau khi thử 2 máy: trước là 3 phút)*. |
| Phòng được tạo lúc nào *(18/11, sau khi thử 2 máy)* | **Chỉ khi người mở bấm "Vào phòng"** ở màn hình chờ. Bấm "Online Meeting" rồi quay lại thì không có phòng nào được tạo (trước đó phòng được tạo ngay lúc bấm nút, để lại "phòng ma" làm người khác thấy nút "Tham gia phòng") |
| Số người tối đa | **6** |
| Trong phòng có gì | Cam, mic, chia sẻ màn hình, danh sách người tham gia. **Không** có chat, không có phụ đề trực tiếp |
| Ghi gì | **Chỉ ghi âm, riêng từng người** (AI không dùng hình; ghi hình rất nặng) |
| Bật ghi âm | **Chủ phòng bấm "Bắt đầu ghi"**; mọi người thấy chấm đỏ "Đang ghi âm" (minh bạch, quyền riêng tư) |
| Ghi mấy lần | **Ghi một mạch**: bấm một lần, ghi tới khi chủ phòng bấm "Dừng ghi" hoặc kết thúc phòng. Đã dừng thì buổi đó không ghi lại |
| Không ai bấm ghi | **Không tạo cuộc họp** trong danh sách. **Không hiện lời nhắc "chưa ghi âm"** — có khi mọi người chỉ gọi nói chuyện, không cần biên bản |
| Cách ghi | **Trình duyệt mỗi người tự ghi mic của mình** (dùng lại bộ ghi âm GĐ3) và **gửi dần lên máy chủ ngay trong lúc họp**. Tắt mic thì đoạn đó là khoảng lặng, mốc thời gian vẫn chạy liên tục |
| Thiếu ghi âm của một người | Phòng kết thúc → **chờ tối đa 2 phút** rồi nhận dạng với những gì đã có, trang cuộc họp ghi "Thiếu ghi âm của …". Phần đến muộn **tự bổ sung** vào bản ghi; nếu bản ghi đã bị sửa tay hoặc đã tóm tắt thì không tự ghi đè mà hiện nút cho người duyệt bấm |
| Sau khi họp xong | **Tự động chuyển giọng nói → văn bản**, bản ghi dạng "Nam: …", "Lan: …". **Tóm tắt vẫn bấm tay** |
| Dùng nhãn người nói | Câu **"để em làm" được giao cho chính người nói** (GĐ4 phải để trống). GĐ7 thêm thí nghiệm có / không có nhãn người nói |
| Tiếng vọng (nghe loa ngoài, mic thu lại tiếng người khác) | **Có bước lọc**: hai người có câu gần giống nhau ở cùng thời điểm → giữ một bản, của người nói gốc |
| Tên nguồn cuộc họp | **"Online Meeting"** |

**Chưa làm ở bản đầu (hướng phát triển):** cho người ở xa họp thật (cần máy chủ có IP công khai / LiveKit Cloud + Cloudflare Tunnel), ghi hình, chat, phụ đề trực tiếp.

Chi tiết và lý do: `docs/GIAI_THICH_GIAI_DOAN_6.md`.
