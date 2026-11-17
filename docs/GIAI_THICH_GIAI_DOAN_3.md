# GIẢI THÍCH GIAI ĐOẠN 3 — TẢI GHI ÂM & CHUYỂN GIỌNG NÓI THÀNH VĂN BẢN

Giai đoạn này làm **bước đầu tiên của pipeline AI** (F09–F12): người dùng tải file ghi âm cuộc họp lên, hệ thống chuyển thành văn bản trên GPU, có thanh tiến độ cập nhật theo thời gian thực. Sau đó người dùng nghe lại, xem và sửa bản ghi.

```
[Trình duyệt] ──upload──► [API] ──lưu file + đưa job vào hàng đợi──► [Redis]
      ▲                                                                  │
      │ WebSocket                                                        ▼
[Backend] ◄──── Redis Pub/Sub: "đã xong 45%" ◄──────────── [Worker AI + GPU: Whisper]
                                                                         │
                                                         lưu bản ghi ──► [PostgreSQL]
```

> **Cách chạy:** cần thêm terminal thứ 3 cho worker AI:
> ```
> cd backend
> .venv\Scripts\activate
> python -m app.workers.worker
> ```
> Worker in ra "Sẵn sàng: faster-whisper/large-v3-turbo" là được.

---

## 1. Dữ liệu: 2 bảng mới

| Bảng | Nội dung | Điểm đáng chú ý |
|---|---|---|
| `meetings` | Tên, ngày họp, nguồn (`audio` hay `text`), thông tin file, **trạng thái**, **% tiến độ**, lỗi | File ghi âm lưu **trên đĩa** (`backend/uploads/meetings/`); CSDL chỉ lưu đường dẫn |
| `transcripts` | Bản ghi: `full_text` và `segments` (JSONB), mô hình đã dùng, thời lượng, thời gian xử lý, `edited` | Quan hệ **1–1** với meetings |

**Vì sao không lưu file ghi âm vào CSDL?** File có thể nặng hàng trăm MB. Nhét vào CSDL làm CSDL phình to, sao lưu chậm và truy vấn chậm. Cách chuẩn là lưu file trên đĩa (hoặc dịch vụ lưu trữ như S3), còn CSDL chỉ giữ đường dẫn.

**Vì sao `segments` dùng JSONB mà không tạo bảng riêng?** Bản ghi luôn được đọc và ghi **cả khối**: hiển thị toàn bộ, sửa rồi lưu toàn bộ. Không cần truy vấn riêng từng câu, nên JSONB đơn giản hơn và nhanh hơn.

### Vòng đời (trạng thái) của một cuộc họp
```
uploaded ──► queued ──► transcribing (0% → 99%) ──► transcribed ──► (GĐ4) tóm tắt...
                              │
                              └──► failed ──(bấm "Thử lại")──► queued
Dán văn bản / file .txt ──────────────────────────► transcribed (bỏ qua bước AI nghe)
```
Lưu trạng thái trong CSDL giúp tải lại trang, tắt trình duyệt hay mở trên máy khác vẫn thấy đúng tình trạng.

---

## 2. Tải file lên

- **3 nguồn đầu vào (F10):** file ghi âm (mp3, m4a, wav, webm, ogg, aac, flac, mp4…), file `.txt`, hoặc **dán văn bản** (khi đã có biên bản sẵn hoặc lấy phụ đề từ Google Meet).
- **Ghi file theo từng khối 1MB** (`save_audio`), không đọc cả file vào RAM. Nhờ vậy file 300MB cũng không làm tràn bộ nhớ server.
- **Kiểm tra đầu vào:** đúng đuôi file, không rỗng, tối đa 300MB, phải chọn **file HOẶC văn bản** (không được cả hai hoặc không có gì).
- **Thanh tiến độ tải lên** ở frontend dùng `onUploadProgress` của axios.

### Phát lại audio
- Thẻ `<audio>` của trình duyệt **không gửi được header** `Authorization`, nên token được truyền qua URL: `/api/meetings/1/audio?token=...`. Server vẫn kiểm tra token và quyền thành viên.
- `FileResponse` hỗ trợ **Range request** (HTTP 206). Trình duyệt chỉ tải đúng đoạn cần nghe, nên **tua tới giữa file** được ngay mà không phải tải hết. Có test riêng kiểm tra điều này (`test_upload_audio_is_queued_and_playable`).

---

## 3. Hàng đợi và worker — xử lý bất đồng bộ

Đây là phần kiến trúc **quan trọng nhất** để trình bày trước hội đồng.

1. API nhận file, lưu, rồi **đưa job vào hàng đợi Redis** (`enqueue_transcription`) và **trả lời ngay** (status `queued`). Toàn bộ chỉ mất dưới 1 giây.
2. **Worker** là chương trình riêng, chạy `python -m app.workers.worker`. Nó lấy job ra và chạy Whisper trên GPU.
3. Worker xử lý **lần lượt từng cuộc họp**, nên GPU 4GB không bao giờ bị tràn bộ nhớ dù nhiều người tải cùng lúc.
4. **Mô hình được nạp một lần** khi worker khởi động (khoảng 5–10 giây) và giữ trong VRAM cho mọi job sau.

**Khi có lỗi** (file hỏng, hết VRAM…): worker bắt lỗi, ghi `status = failed` kèm lý do. Người dùng thấy lỗi và bấm **"Thử lại"**. Nếu chưa bật Redis (Docker), API cũng không bị sập mà ghi lỗi rõ ràng "Hãy bật Docker rồi bấm Thử lại".

---

## 4. Tiến độ realtime: Redis Pub/Sub

**Vấn đề:** WebSocket ở Giai đoạn 2 chỉ dùng được **trong cùng tiến trình backend**. Worker là **tiến trình khác**, nên không gửi thẳng vào WebSocket được.

**Giải pháp: Redis Pub/Sub (Publish/Subscribe):**
```
Worker: publish("meetflow:events", {room: "workspace:1", status: "transcribing", progress: 45})
                         │
                       Redis  (bưu điện trung gian)
                         │
Backend: subscribe("meetflow:events")  ← tác vụ nền chạy từ lúc backend khởi động (lifespan)
   └──► gửi tới mọi WebSocket trong phòng "workspace:1" ──► thanh tiến độ trên trình duyệt nhích lên
```
- **Phòng** `workspace:<id>`: ai đang mở trang nhóm hoặc trang cuộc họp thì nhận tiến độ.
- **Không spam:** worker chỉ báo tiến độ khi tăng ít nhất 1% **và** cách lần trước ít nhất 1 giây.
- **Frontend cập nhật thông minh** (`useWorkspaceSocket`): nếu chỉ đổi % thì sửa thẳng vào cache, không gọi API, nên thanh tiến độ mượt. Nếu đổi trạng thái (ví dụ xong) thì tải lại dữ liệu đầy đủ, kèm bản ghi.
- **Dự phòng:** nếu WebSocket mất kết nối, trang cuộc họp tự hỏi server **mỗi 5 giây** (polling) trong lúc đang xử lý.

**Lợi ích phụ:** đây cũng là cách để sau này chạy **nhiều tiến trình backend**, vì mọi tiến trình đều nghe Redis. Giới hạn đã nêu ở Giai đoạn 2 được giải quyết một phần.

---

## 5. Cải tiến chất lượng nhận dạng

### 5.1. Gợi ý tên thành viên cho Whisper (`initial_prompt`)
Trước khi nghe, worker tạo câu gợi ý từ danh sách thành viên và biệt danh:
> "Cuộc họp nhóm. Thành viên: Nguyễn Văn Nam (Nam, anh Nam), Trần Thị Lan (Lan, chị Lan), Lê Quang Minh (Minh)."

Whisper coi câu này là "đoạn văn phía trước", nên **có xu hướng viết đúng các tên này**.

**Kết quả thực tế (cùng một file ghi âm, chạy trên RTX 3050):**
| | Không có gợi ý (Giai đoạn 0) | Có gợi ý tên (Giai đoạn 3) |
|---|---|---|
| "Nam" | ❌ "NOM" | ✅ "Nam" |
| "Lan" | ❌ "LAN" | ✅ "Lan" |
| "Minh" | ❌ "MIN" | ⚠️ "Min" (gần đúng) |

Đây là **số liệu cụ thể cho chương thực nghiệm**, và là bằng chứng cho thấy đề tài không chỉ gọi API mà có **cải tiến dựa trên ngữ cảnh** của hệ thống.

#### ⚠️ Tác dụng phụ đã gặp: Whisper "chép lại gợi ý" (prompt echo)
**Lỗi thật khi thử:** một file ghi âm 7 giây nói không rõ cho ra bản ghi đúng một câu **"Nguyễn Văn Nam"**, dù người nói không hề nhắc tên này. Whisper không chắc mình nghe gì nên **chép luôn chữ trong gợi ý** ra làm kết quả.

| Chạy | Kết quả |
|---|---|
| Có gợi ý tên | `Nguyễn Văn Nam` (bịa) |
| Không gợi ý | `Ờ, Dead Life còn đảm là` (nghe chưa rõ, nhưng là lời thật) |

**Cách xử lý** (`is_prompt_echo`): câu nào **chỉ gồm toàn chữ có trong gợi ý** thì bị nghi là chép gợi ý. Khi đó hệ thống **chạy lại không dùng gợi ý** và lấy kết quả lần chạy sau. Worker ghi log `Whisper chép lại gợi ý tên → đã chạy lại không dùng gợi ý`. Câu thật có nhắc tên, như *"Nam làm phần cơ sở dữ liệu"*, vẫn được giữ vì có chữ ngoài gợi ý. Cuộc họp mẫu 85 giây không bị ảnh hưởng, vẫn ra 25 câu.

**Bài học khi bảo vệ:** một cải tiến cũng có thể sinh lỗi mới. Cần **thử với dữ liệu xấu** (file ngắn, nói không rõ, file nhạc) chứ không chỉ dữ liệu đẹp, và có cơ chế **phát hiện rồi tự sửa**.

### 5.2. Tách câu theo mốc thời gian từng từ
Whisper trả về các "đoạn" dài tới 30 giây, có khi **cả bài nói thành 1 đoạn**. Bật `word_timestamps=True` thì có mốc thời gian **của từng từ**, rồi hàm `split_sentences` cắt tại dấu `. ? !` thành **từng câu có mốc riêng**:
```
Trước:  [0:00–0:18] Good morning everyone. Let's start... Thank you, see you next week.
Sau:    [0:00] Good morning everyone.
        [0:01] Let's start the weekly meeting.
        [0:04] Nam will finish the database design by next Friday.
        ...  (6 câu)
```
Lợi ích: bấm vào câu nào thì audio tua đúng câu đó. Ở Giai đoạn 4, AI **trích dẫn được chính xác câu gốc** làm bằng chứng cho từng đầu việc.

### 5.3. Chặn "ảo giác" (hallucination) của Whisper
**Lỗi gặp thật khi chạy thử:** file ghi âm tiếng Anh 18 giây, nhưng bản ghi có thêm câu cuối:
> *"Hãy subscribe cho kênh La La School Để không bỏ lỡ những video hấp dẫn"*

File **không hề có câu này**. Whisper được huấn luyện trên rất nhiều video YouTube có câu chào cuối video, nên khi gặp **đoạn im lặng / tiếng ồn** nó có xu hướng **tự bịa** ra những câu kiểu đó. Hiện tượng này đặc biệt hay gặp với tiếng Việt.

**Nguy hiểm với đề tài:** câu bịa có thể bị AI ở Giai đoạn 4 hiểu nhầm thành nội dung cuộc họp.

**Ba lớp chặn** (`ai/stt/faster_whisper_provider.py`):
| Lớp | Cách làm |
|---|---|
| 1. `hallucination_silence_threshold=2.0` | Tham số có sẵn của faster-whisper: gặp khoảng lặng > 2 giây mà nghi ảo giác thì bỏ qua khoảng đó |
| 2. Lọc theo độ tin cậy | Câu có `no_speech_prob > 0.6` (mô hình cho rằng nhiều khả năng không có tiếng nói) **và** `avg_logprob < -0.8` (không tự tin vào chữ sinh ra) thì bỏ |
| 3. Danh sách câu ảo giác đã biết | So khớp **không dấu, không phân biệt hoa thường**: "subscribe", "đăng ký kênh", "cảm ơn các bạn đã theo dõi", "La La School", "Ghiền Mì Gõ", "phụ đề bởi"… |

**Kết quả:** chạy lại cùng file thì câu bịa bị lọc. Worker ghi log `đã lọc 1 câu nghi ảo giác: [...]`. Có test `test_hallucination_filter` dùng chính câu bịa thật này.

**Thử với file NHẠC (bài hát 4 phút):** VAD coi gần hết là "không phải lời nói" nên bỏ đi; phần còn lại Whisper bịa ra "Hãy subscribe cho kênh Ghiền Mì Gõ…"; bộ lọc chặn đúng câu này nên còn 0 câu. Hệ thống báo lỗi rõ ràng *"Không nhận ra lời nói trong file ghi âm. File có thể là nhạc, im lặng, hoặc quá ồn"* thay vì hiện "Đã có bản ghi" mà trống trơn (test `test_no_speech_detected_is_reported_as_failed`).

**Khi hội đồng hỏi "AI bịa thì sao?":** em đã gặp, đã đo và có 3 lớp chặn ở bước nghe. Ở bước tóm tắt (Giai đoạn 4) còn thêm bước **trích dẫn câu gốc** và **con người duyệt** trước khi tạo công việc.

### 5.4. Các tham số khác
| Tham số | Ý nghĩa |
|---|---|
| `language="vi"` | Không bắt mô hình đoán ngôn ngữ, nên nhanh và chính xác hơn |
| `vad_filter=True` | Bỏ đoạn im lặng (Silero VAD): nhanh hơn, giảm "bịa chữ" khi im lặng |
| `condition_on_previous_text=False` | Không dựa vào câu trước để giải mã câu sau, tránh lỗi **lặp một câu vô tận** hay gặp với file dài |
| `beam_size=5` | Tìm kiếm chùm, giữ 5 phương án song song khi sinh chữ |
| `int8_float16` | Lượng tử hóa, vừa GPU 4GB |

---

## 6. Giao diện

| Màn hình | Chức năng |
|---|---|
| **Trang nhóm → khối "Cuộc họp"** | Danh sách cuộc họp, trạng thái tự cập nhật (realtime), nút "Thêm cuộc họp" |
| **Hộp "Thêm cuộc họp"** | Kéo-thả file hoặc dán văn bản, thanh tiến độ tải lên |
| **Trang cuộc họp** `/meetings/:id` | Các bước xử lý (pipeline), thanh % tiến độ, trình phát audio, bản ghi |
| **Bản ghi** | Bấm mốc thời gian để nghe đúng câu đó; **câu đang phát được tô sáng** và tự cuộn theo; chế độ **sửa bản ghi** |
| **Thông tin** | Thời lượng, thời gian xử lý, tốc độ (×6 = nhanh gấp 6 lần thời gian thực), mô hình, đã sửa tay hay chưa; sao chép / tải `.txt` |

**Vì sao cho sửa bản ghi (F12)?** Kết quả AI không bao giờ hoàn hảo, nhất là **tên riêng và ngày tháng**, mà đây lại chính là thông tin "Ai làm – Hạn chót" của đầu việc. Sửa ở bước này thì Giai đoạn 4 trích xuất đúng hơn. Đây là thiết kế **human-in-the-loop** (con người kiểm soát kết quả AI). Cờ `edited` cũng giúp chương thực nghiệm phân biệt bản ghi gốc với bản đã sửa.

**Đồng bộ audio và bản ghi:** lắng nghe sự kiện `timeupdate` của thẻ `<audio>`, tìm câu có `start ≤ thời điểm hiện tại` rồi tô sáng câu đó.

---

## 7. Dữ liệu thử nghiệm tiếng Việt: `experiments/make_sample_meeting.py`

Script **tự sinh một cuộc họp tiếng Việt giả lập** (3 người: Nam, Lan, Minh) bằng giọng đọc của Microsoft Edge (edge-tts), kèm sẵn **đáp án chuẩn**:
- `reference.txt`: bản ghi đúng, dùng để tính **WER** ở Giai đoạn 6.
- `expected_tasks.json`: 4 đầu việc đúng (ai, việc gì, hạn chót), dùng để chấm bước trích xuất ở Giai đoạn 4.

Vì biết trước chính xác "đáp án", bộ dữ liệu này dùng được để **đo độ chính xác** một cách khách quan.

### Kết quả đo thật (16/11/2026, RTX 3050 Laptop 4GB, `large-v3-turbo` int8)

| Chỉ số | Kết quả |
|---|---|
| Thời lượng ghi âm | 85,0 giây, 3 người nói, 14 lượt lời |
| Thời gian xử lý | **3,6 giây**, nhanh gấp **23 lần** thời gian thực |
| Số câu sau khi tách | 25 |
| **WER thô** | 6,69% (16 lỗi / 239 từ) |
| **WER sau chuẩn hóa số** | **2,09%** (5 lỗi / 239 từ) |

Chạy lại bằng: `python experiments/eval_wer.py --meeting <id> experiments/data/sample_meeting_01/reference.txt`

**Vì sao có 2 con số WER?** Whisper hay viết số bằng **chữ số** ("thứ 6", "ngày 25 tháng 11"), trong khi bản chuẩn viết bằng chữ ("thứ sáu", "hai mươi lăm"). Về nghĩa thì **không sai**, nên `eval_wer.py` đổi chữ số thành chữ (hàm `number_to_vi`) trước khi so. Báo cáo cả hai con số để minh bạch. Viết số bằng chữ số còn **có lợi** cho Giai đoạn 4, vì AI và code đọc hạn chót "25/11" dễ hơn.

**5 lỗi thật còn lại:**
| Chuẩn | Whisper nghe | Loại lỗi |
|---|---|---|
| bảng | bản | Gần âm (thanh hỏi / không dấu) |
| hạn | hạng | Gần âm |
| large | lát | Từ tiếng Anh xen trong câu tiếng Việt |
| card | cạt | Từ tiếng Anh xen trong câu tiếng Việt |
| **Minh** | **mình** | **Tên người bị nhầm thành đại từ**, ảnh hưởng trực tiếp tới "Ai làm" ở Giai đoạn 4 |

Lỗi cuối cho thấy tên riêng tiếng Việt trùng với từ thông dụng (Minh/mình, Nam/năm, Lan/lan…) là **thách thức thật**. Đây là lý do có bước **sửa bản ghi**, **biệt danh** và **màn hình duyệt** trước khi tạo công việc.

**Hạn chế cần nói thật:** giọng máy đọc rõ ràng hơn người thật (không ồn, không nói chen). Kết quả trên dữ liệu này là **cận trên**; cần bổ sung ghi âm người thật ở Giai đoạn 6. Ngoài ra dịch vụ đọc miễn phí này khá chập chờn, nên script có cơ chế thử lại nhiều lần.

---

## 7b. Ghi âm trực tiếp trên trình duyệt (E1) + chống mất dữ liệu

Người dùng bấm **"● Ghi âm trực tiếp"** ngay lúc họp, không cần ghi bằng điện thoại rồi chép file sang.

```
Micro ──getUserMedia──► MediaRecorder ──mỗi 1 giây 1 khúc──► IndexedDB (bộ nhớ trình duyệt)
                                                                  │
                                       Bấm "Dừng & xử lý" ──ghép khúc──► tải lên server
                                                                  │
                                     Thành công → xóa bản tạm │ Thất bại → GIỮ LẠI, chờ có mạng
```

| Thành phần | Vai trò |
|---|---|
| `getUserMedia` | Xin quyền dùng micro; bật **khử tiếng vọng, giảm ồn, tự cân bằng âm lượng** (hợp với phòng họp) |
| `MediaRecorder` | Ghi âm thành webm/opus 64kbps (1 giờ ≈ 28MB). Safari thì tự chuyển sang mp4 |
| `AnalyserNode` (Web Audio API) | Đo âm lượng, vẽ **thanh mức âm** để biết micro có đang thu tiếng không |
| **IndexedDB** (`lib/recordingStore.ts`) | Lưu **từng khúc 1 giây** ngay khi ghi, không mất khi tải lại trang, đóng tab hay tắt máy |
| Wake Lock | Giữ màn hình không tự tắt khi đang ghi |
| `beforeunload` | Cảnh báo nếu lỡ đóng tab khi đang ghi |

### Cơ chế dự phòng (fallback) khi mất mạng
1. Ghi xong mà tải lên **lỗi** (mất mạng, server sập): bản ghi **vẫn nằm trong IndexedDB**, và hiện ở mục **"⚠️ Bản ghi âm chưa tải lên"** trên trang nhóm.
2. Trình duyệt báo **có mạng lại** (sự kiện `online`): **tự tải lên**, không cần bấm gì.
3. Đang ghi mà **trang bị đóng / sập**: phần đã ghi vẫn còn (đánh dấu "bị gián đoạn khi đang ghi"), có thể tải lên bình thường.
4. **Chỉ xóa bản tạm khi server đã nhận thành công.** Đây là nguyên tắc quan trọng nhất.

### Sửa thời lượng file webm (backend)
File webm do trình duyệt ghi **không có thông tin độ dài** (ghi theo luồng, không biết trước khi nào dừng), nên trình phát hiện "vô cực" và không tua được. Worker **remux** file (đóng gói lại, *không mã hóa lại*, chất lượng giữ nguyên, rất nhanh) để ghi đúng độ dài và bảng mục lục (`fix_webm_duration`).

### Kết quả kiểm thử thật trên trình duyệt
| Kịch bản | Kết quả |
|---|---|
| Ghi 46 giây (micro được thay bằng luồng phát cuộc họp mẫu) | 37 khúc lưu vào IndexedDB sau 38 giây; tải lên; worker xử lý **4,9 giây**; bản ghi đúng nội dung |
| Trình phát sau khi remux | Thời lượng **46,3 giây**, tua được toàn bộ (trước khi sửa: "vô cực") |
| **Giả lập mất mạng** lúc bấm dừng | Báo "Chưa tải lên được… vẫn được giữ trên máy này"; hiện trong mục "Bản ghi chưa tải lên" |
| **Có mạng lại** | Tự tải lên trong vài giây, mục cảnh báo biến mất, cuộc họp chuyển sang "Đã có bản ghi" |

**Chưa thử trên trình duyệt:** kịch bản *đóng tab giữa lúc đang ghi*. Logic dùng chung kho IndexedDB nên kỳ vọng hoạt động, nhưng nên tự thử: ghi 10 giây, tải lại trang, rồi xem mục "Bản ghi chưa tải lên".

**Giới hạn:** trình duyệt chỉ cho dùng micro trên **https** hoặc **localhost**. Mở bằng địa chỉ IP trong mạng LAN (ví dụ `http://192.168.1.5:5173`) thì không ghi âm được, khi triển khai thật phải có https.

---

## 8. Kiểm thử

**29 test tự động** (thêm 15 test so với Giai đoạn 2). Worker dùng **bộ STT giả** (`FakeSTT`), nên test chạy vài giây và không cần GPU:

| Test | Kiểm tra |
|---|---|
| `test_create_from_pasted_text`, `test_create_from_txt_file` | Tạo từ văn bản và file .txt (kể cả có BOM UTF-8) |
| `test_validation` | Không file / sai đuôi / vừa file vừa text / người ngoài nhóm |
| `test_upload_audio_is_queued_and_playable` | Tải lên → `queued`; phát lại đúng nội dung; **Range request trả 206**; người ngoài bị chặn |
| `test_worker_job_success_with_member_names_prompt` | Worker lưu bản ghi đúng; **gợi ý tên + biệt danh** được đưa vào Whisper |
| `test_worker_job_failure_then_retry` | Lỗi (giả lập hết VRAM) → `failed` có lý do → Thử lại → `queued`; không cho thử lại khi đang chờ |
| `test_edit_transcript_and_delete` | Sửa bản ghi (bỏ đoạn rỗng, đánh dấu `edited`); xóa cuộc họp thì **xóa cả file** |
| `test_job_skips_deleted_meeting` | Cuộc họp bị xóa trong lúc chờ thì worker bỏ qua, không lỗi |
| `test_split_into_sentences...` | Tách câu đúng mốc thời gian; câu quá ngắn ("Dạ.") được nối vào câu trước |
| `test_hallucination_filter` | Lọc câu ảo giác thật ("Hãy subscribe cho kênh La La School…"), giữ câu bình thường |
| `test_prompt_echo_detection` | Phát hiện Whisper chép lại tên trong gợi ý ("Nguyễn Văn Nam"), giữ câu thật có nhắc tên |
| `test_no_speech_detected_is_reported_as_failed` | File nhạc / im lặng thì báo lỗi rõ ràng, không "có bản ghi" rỗng |
| `test_fix_webm_duration` | File webm/opus sau khi remux có đúng thời lượng |
| `test_recorded_source_type` | Ghi trực tiếp được đánh dấu nguồn `recording` |

**Kiểm thử thật trên máy (GPU RTX 3050):**
- Tải file, worker xử lý xong trong khoảng 3 giây với file 18,6 giây (×6 thời gian thực).
- Trang nhóm tự đổi trạng thái "Đang chuyển giọng nói" sang "Đã có bản ghi" mà **không cần tải lại**.
- Trình phát audio phát được, tua được.

---

## Tự kiểm tra

1. Vì sao không lưu file ghi âm trong CSDL?
2. Vì sao API trả về ngay mà không chờ Whisper chạy xong? Worker chạy ở đâu?
3. Worker là tiến trình khác, vậy làm sao báo tiến độ lên trình duyệt? Redis Pub/Sub hoạt động thế nào?
4. Vì sao thẻ `<audio>` phải truyền token qua URL? Range request (HTTP 206) giúp gì?
5. `initial_prompt` là gì? Nó cải thiện điều gì, có số liệu không?
6. Vì sao cần `word_timestamps` và tách câu?
7. Vì sao cho người dùng sửa bản ghi trước khi tóm tắt?
8. Nếu worker đang chạy mà người dùng xóa cuộc họp thì sao?
9. "Ảo giác" của Whisper là gì, vì sao xảy ra? Hệ thống chặn bằng mấy lớp?
10. Ghi âm trực tiếp mà mất mạng hoặc lỡ đóng tab thì có mất bản ghi không? IndexedDB giúp gì?
11. Vì sao file webm từ trình duyệt không tua được, và hệ thống sửa thế nào?
