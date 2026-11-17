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
| F04 | Bảng công việc | Mỗi nhóm có nhiều bảng, mặc định 3 cột Cần làm / Đang làm / Hoàn thành |
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
- [ ] Cài Docker Desktop, lấy Gemini API key
- [ ] Khởi tạo repo Git, cấu trúc thư mục, Docker Compose (PostgreSQL + Redis)
- [ ] Khung FastAPI + khung React chạy được "Hello"
- [ ] Chạy thử faster-whisper trên GPU với 1 file mẫu
- **Kiến thức cần nắm:** kiến trúc client–server, REST API, Docker là gì, vì sao chọn FastAPI

### Giai đoạn 1 – Phân tích thiết kế (Tuần 2: 23/11 – 29/11)
- [ ] Khảo sát sản phẩm tương tự: Trello, Jira, Notion AI, Otter.ai, Fireflies.ai
- [ ] Vẽ use case, sơ đồ hoạt động của pipeline AI, ERD, sơ đồ tuần tự "upload → task"
- [ ] Wireframe các màn hình chính
- **Kiến thức cần nắm:** UML, chuẩn hóa CSDL, vì sao thiết kế human-in-the-loop

### Giai đoạn 2 – Phân hệ quản lý (Tuần 3–5: 30/11 – 20/12)
- [ ] Auth JWT, user, workspace, mời thành viên (F01–F03)
- [ ] Board, column, task, comment, API + giao diện (F04–F05)
- [ ] Kéo-thả + lưu thứ tự + WebSocket realtime (F06)
- [ ] Lọc, tìm kiếm, thông báo (F07–F08)
- **Kiến thức cần nắm:** JWT hoạt động thế nào, băm mật khẩu bcrypt, WebSocket so với polling, cách lưu thứ tự thẻ khi kéo-thả

### Giai đoạn 3 – STT (Tuần 6–7: 21/12 – 03/01)
- [ ] API upload + lưu file + tạo meeting (F09–F10)
- [ ] Redis + RQ worker, cập nhật trạng thái, đẩy % tiến độ qua WebSocket
- [ ] ffmpeg + faster-whisper, lưu segments (F11)
- [ ] Giao diện xem/sửa bản ghi, phát audio theo đoạn (F12)
- **Kiến thức cần nắm:** Whisper hoạt động thế nào (encoder–decoder Transformer, log-Mel spectrogram), VAD, lượng tử hóa int8, hàng đợi bất đồng bộ

### Giai đoạn 4 – LLM tóm tắt & trích xuất (Tuần 8–9: 04/01 – 17/01)
- [ ] Thiết kế prompt + JSON schema, gọi Gemini (F13–F14)
- [ ] Chunking cho bản ghi dài
- [ ] Ghép tên (rapidfuzz) và chuẩn hóa ngày tiếng Việt (F15–F16)
- [ ] Provider Ollama để so sánh
- **Kiến thức cần nắm:** LLM là gì, prompt engineering, structured output, hallucination và cách giảm (trích dẫn câu gốc, con người duyệt)

### Giai đoạn 5 – Duyệt & đẩy lên bảng (Tuần 10: 18/01 – 24/01)
- [ ] Màn hình duyệt, nút "Đẩy lên bảng" tạo nhiều task trong 1 transaction (F17)
- [ ] Lịch sử họp, xuất PDF/DOCX (F18–F19)

### Giai đoạn 6 – Thực nghiệm (Tuần 11: 25/01 – 31/01)
- [ ] Thu, gán nhãn dữ liệu, viết script đánh giá, chạy 3 thí nghiệm, vẽ biểu đồ
- **Kiến thức cần nắm:** WER, Precision / Recall / F1, cách đọc và giải thích kết quả

### Giai đoạn 7 – Hoàn thiện (Tuần 12: 01/02 – 07/02)
- [ ] Kiểm thử (pytest cho backend, kiểm thử thủ công theo kịch bản), sửa lỗi
- [ ] Seed dữ liệu demo, quay video demo dự phòng
- [ ] (Tuỳ chọn) deploy: Vercel + Render + Neon, STT qua Groq

### Giai đoạn 8 – Báo cáo & bảo vệ (Tuần 13–14: 08/02 – 21/02)
- [ ] Viết báo cáo, làm slide, luyện bộ câu hỏi bảo vệ (mục 10)

> Tết Nguyên đán 2027 rơi vào khoảng 06/02/2027, nên giai đoạn 7–8 có thể bị lùi. Nên làm nhanh giai đoạn 2–5 để có dư thời gian.

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
| F21 | Gộp tên vào tài khoản | Khi Duy đăng ký + vào nhóm → chọn gộp các thẻ tên "Duy" vào tài khoản của Duy |
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
