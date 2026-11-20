# GIẢI THÍCH GIAI ĐOẠN 6 — PHÒNG HỌP TRỰC TUYẾN "ONLINE MEETING"

Giai đoạn này thêm **nguồn cuộc họp thứ ba**: họp ngay trong MeetFlow. Điểm ăn tiền không phải là "có gọi video", mà là: **mỗi người có một file ghi âm riêng**, nên hệ thống biết chắc *ai nói câu nào*.

```
Trang nhóm ──"📹 Online Meeting"──► màn hình chờ ──"Vào phòng"──► PHÒNG HỌP (cam / mic / chia sẻ màn hình)
                                                                        │ chủ phòng bấm "● Bắt đầu ghi"
                     trình duyệt MỖI NGƯỜI tự ghi mic của mình, gửi dần từng khúc 3 giây lên máy chủ
                                                                        │ "Kết thúc cho mọi người"
   track của Nam ─► Whisper ─┐
   track của Lan ─► Whisper ─┼─► dời mốc thời gian ─► trộn theo thời gian ─► lọc tiếng vọng
   track của Minh ► Whisper ─┘                                │
                                       bản ghi "Nguyễn Văn Nam: … / Trần Thị Lan: …" ──► GĐ4 (tóm tắt) ──► GĐ5 (duyệt, lên bảng)
```

| Việc | Trạng thái |
|---|---|
| LiveKit (Docker) + HTTPS tự ký, phòng họp cam / mic / chia sẻ màn hình | ✅ |
| Ghi âm riêng từng người, gửi dần lên máy chủ, gửi nốt khi rớt mạng | ✅ |
| Bản ghi có tên người nói, lọc tiếng vọng, file nghe lại đã trộn | ✅ |
| "Để em làm" → giao cho chính người nói | ✅ |
| Thử với **hai máy thật** qua Wi-Fi (mic thật, cam, chia sẻ màn hình) | ⏳ người làm khóa luận tự thử — xem mục 10 |

Mọi quyết định sản phẩm (ai được vào, ai được ghi, chờ bao lâu…) nằm ở **mục 17 của `KE_HOACH_PHUONG_AN_B.md`**. File này giải thích *cách làm* và *vì sao*.

---

## 0. Cách chạy

**Chỉ thử trên máy mình** (localhost vẫn bật được cam / mic):
```
docker compose up -d          # thêm container meetflow-livekit
cd backend && alembic upgrade head      # 2 bảng mới
# khởi động lại Backend API + Worker AI, rồi npm run dev như cũ → http://localhost:5173
```

**Cho máy khác trong cùng Wi-Fi vào họp** (demo bảo vệ):
```
backend\.venv\Scripts\python scripts\setup_lan.py     # dò IP máy, tạo khóa LiveKit + chứng chỉ HTTPS tự ký
docker compose up -d                                   # nạp lại LiveKit với IP mới
# khởi động lại Backend API (đọc khóa mới trong backend/.env)
cd frontend && npm run dev:lan                         # https://<IP-máy>:5173
```
Mọi người mở `https://<IP-máy>:5173` → lần đầu bấm **Nâng cao → Vẫn tiếp tục** (chứng chỉ tự ký). Đổi Wi-Fi / phát hotspot thì IP đổi → chạy lại `setup_lan.py` và `docker compose up -d`.

**Tường lửa Windows** (tự cho phép, hệ thống không tự sửa cài đặt bảo mật): lần đầu chạy `npm run dev:lan`, Windows hỏi cho Node.js nhận kết nối → chọn cho phép mạng riêng. Nếu máy khác vào được web nhưng không thấy hình / tiếng, mở thêm cổng **7881 (TCP)** và **7882 (UDP)** cho Docker.

---

## 1. Kiến thức nền: WebRTC, SFU, vì sao phải HTTPS

**WebRTC** là công nghệ có sẵn trong trình duyệt để gửi hình / tiếng theo thời gian thực (không cần cài gì). Ba khái niệm cần nắm:

| Khái niệm | Ý nghĩa | Trong MeetFlow |
|---|---|---|
| **Tín hiệu (signaling)** | Hai bên "bắt tay": tôi có cam gì, mã hóa gì, địa chỉ nào | WebSocket `wss://<máy>:5173/rtc` (Vite chuyển tiếp tới LiveKit cổng 7880) |
| **ICE** | Thử các đường đi để tìm đường gửi hình / tiếng tới nhau | Trong LAN đi thẳng tới `IP-laptop:7882` (UDP). Ra Internet mới cần STUN / TURN |
| **SFU** | Máy chủ nhận luồng của mỗi người MỘT lần rồi chuyển tiếp cho người khác | **LiveKit** (mã nguồn mở, chạy bằng Docker) |

**Vì sao cần SFU mà không để các máy gửi thẳng cho nhau (mesh)?** 6 người gửi thẳng cho nhau là 6 × 5 = 30 luồng, mỗi máy phải mã hóa và tải lên 5 lần → laptop yếu và Wi-Fi không chịu nổi. Với SFU mỗi máy chỉ tải lên 1 lần.

**Vì sao không tự viết máy chủ WebRTC?** Riêng phần này là vài tháng công (ICE, DTLS-SRTP, ước lượng băng thông, simulcast). Đề tài là *biến cuộc họp thành công việc*, không phải làm lại Google Meet. Dùng LiveKit để dành công sức cho phần đóng góp riêng: ghi âm theo người, ghép bản ghi, lọc tiếng vọng, giao việc cho người nói.

**Vì sao bắt buộc HTTPS?** Đây là luật của trình duyệt: `getUserMedia` (cam / mic) chỉ chạy trong *secure context* = `https://` hoặc `localhost`. Máy khác mở `http://192.168.1.100:5173` sẽ không bật được mic. Chứng chỉ thật phải do một tổ chức (CA) cấp cho tên miền; trong LAN ta **tự ký** bằng OpenSSL → kết nối vẫn mã hóa bình thường, chỉ là trình duyệt không tin sẵn nên phải bấm chấp nhận một lần. (Không dùng mkcert vì nó cài một CA gốc vào Windows — thay đổi cài đặt bảo mật của máy.)

**Một địa chỉ duy nhất.** Trình duyệt chỉ nói chuyện với `https://<máy>:5173`; Vite chuyển tiếp `/api` → FastAPI (8000) và `/rtc` → LiveKit (7880). Nhờ vậy chỉ cần MỘT chứng chỉ, bấm chấp nhận MỘT lần, không dính CORS. Chỉ riêng hình / tiếng đi thẳng tới LiveKit qua UDP 7882 (WebRTC tự mã hóa bằng DTLS-SRTP, không cần chứng chỉ web).

---

## 2. Vé vào phòng — `core/livekit.py`

Backend MeetFlow **không đụng tới hình / tiếng**. Nó chỉ làm 2 việc với LiveKit:

1. **Cấp vé (token).** Vé là một JWT ký bằng khóa bí mật mà chỉ backend và LiveKit biết:
   ```json
   { "iss": "<API key>", "sub": "12", "name": "Trần Thị Lan",
     "video": { "roomJoin": true, "room": "NHDhkKgwc7FO", "canPublish": true, "canSubscribe": true } }
   ```
   LiveKit kiểm tra chữ ký là tin "người cầm vé là user 12, được vào phòng này" mà không cần hỏi lại backend. → **Quyền vào phòng do MeetFlow quyết định** (phải đăng nhập, phòng còn mở, chưa đủ 6 người). Đây đúng là cơ chế JWT của GĐ2, dùng cho một hệ thống thứ hai.
2. **Quản lý phòng** qua API của LiveKit (chuẩn Twirp = POST + JSON): tạo phòng, xóa phòng (= mời mọi người ra), đếm người, ghi trạng thái ghi âm vào "metadata" của phòng. Không thêm thư viện nào: dùng `httpx` + `pyjwt` đã có.

`auto_create: false` trong `livekit.yaml`: có vé hợp lệ mà phòng không do backend tạo thì LiveKit vẫn từ chối.

---

## 3. Dữ liệu (migration `8476ac713182`)

| Bảng | Ý nghĩa |
|---|---|
| `meeting_rooms` | Một **buổi** họp trực tuyến: mã link, chủ phòng, trạng thái `open / ended`, mốc bắt đầu / dừng ghi, cuộc họp sinh ra |
| `meeting_tracks` | Ghi âm của **một người** trong buổi đó: file, số khúc đã nhận, thời điểm bắt đầu, kết quả nhận dạng riêng |

Phòng và nhóm tách biệt: **nhóm** lâu dài, **phòng** chỉ sống trong buổi họp (mỗi buổi một link mới). Buổi có ghi âm → khi kết thúc sinh ra một dòng `meetings` với `source_type = "online"` và đi tiếp đúng pipeline cũ. Buổi không ghi âm → không sinh ra gì (đã chốt: có khi mọi người chỉ gọi nói chuyện).

**Mỗi nhóm chỉ một phòng mở — chặn ở CSDL:**
```sql
CREATE UNIQUE INDEX uq_open_room_per_workspace ON meeting_rooms (workspace_id) WHERE status = 'open';
```
Đây là *chỉ mục duy nhất có điều kiện* (partial unique index). Hai người bấm "Online Meeting" cùng một lúc: code kiểm tra "đã có phòng chưa" có thể cùng thấy "chưa", nhưng CSDL chỉ cho một dòng được ghi; người đến sau nhận lỗi và được trả về phòng của người đến trước. → Câu trả lời cho "làm sao chống tạo trùng khi 2 request đồng thời?".

Các đoạn trong bản ghi (`transcripts.segments`) có thêm `speaker`, `speaker_id`, `track_id`, `rms`. Cuộc họp thường không có các khóa này.

---

## 4. Vòng đời phòng — `services/room_service.py`

| Bước | Chi tiết |
|---|---|
| Mở phòng | Thành viên nào cũng mở được; người mở là **chủ phòng**. Bấm "📹 Online Meeting" chỉ đưa tới màn hình chờ (`/room/new?ws=<nhóm>`); **phòng chỉ được tạo khi bấm "Vào phòng"** → bấm nhầm rồi quay lại không để lại phòng trống. Đang có phòng mở → nút trên trang nhóm là **"Tham gia phòng"** |
| Vào bằng link `/room/<mã>` | Chưa đăng nhập → đăng nhập / đăng ký rồi quay lại đúng link. Chưa ở trong nhóm → **tự được thêm vào nhóm** (như Google Meet), rồi mới cấp vé |
| Màn hình chờ | Xem trước, chọn mic / cam. Mặc định **mic bật, cam tắt**. Phòng đang ghi âm thì báo trước ở đây |
| Giới hạn 6 người | Backend đếm người trong phòng trước khi cấp vé (báo "Phòng đã đủ 6 người"); LiveKit cũng chặn ở tầng dưới |
| Ai điều khiển | **Chủ phòng + trưởng nhóm**: bắt đầu / dừng ghi, kết thúc phòng. Hai vai trò có nhãn riêng trong danh sách người tham gia |
| Chủ phòng bấm "Rời phòng" | Hỏi lại: **"Chỉ mình tôi rời"** (quyền chủ phòng chuyển ngay cho người vào sớm nhất còn lại) hay **"Kết thúc cho mọi người"**. Là người cuối cùng thì rời = kết thúc |
| Chủ phòng mất mạng / mất điện | Phòng và ghi âm vẫn tiếp tục. Vắng quá **1 phút** thì nhượng quyền; vào lại kịp thì vẫn là chủ phòng |
| Ghi âm | **Một mạch**: `idle → on → stopped`. Dừng rồi thì buổi đó không ghi lại (mốc thời gian chỉ có một gốc → ghép lời đơn giản, ít lỗi) |
| Kết thúc | Chủ phòng / trưởng nhóm bấm, hoặc **tự đóng** khi mọi người rời hết quá 30 giây. |

**Báo "đang ghi âm" cho mọi người bằng cách nào?** Backend ghi `{"recording": "on"}` vào metadata của phòng trên LiveKit → LiveKit đẩy ngay cho mọi trình duyệt trong phòng (sự kiện `RoomMetadataChanged`). Người vào sau cũng nhận được metadata hiện tại. Mọi người thấy chấm đỏ + dòng "Buổi họp đang được ghi âm…" — minh bạch về quyền riêng tư.

**Nhượng quyền chủ phòng** (quyết định 18/11 sau khi thử hai máy thật). Vấn đề gặp phải: chủ phòng bấm "Rời phòng" thay vì "Kết thúc" → phòng treo, không ai tắt được. Hai đường xử lý:
- *Chủ động rời* (`POST /rooms/{code}/leave`, hàm `leave_room`): chuyển quyền **ngay**, vì đã biết chắc chủ phòng muốn đi.
- *Mất kết nối* (không bấm gì): tác vụ nền thấy chủ phòng không có trong danh sách của LiveKit → ghi `host_absent_since`; quá `ROOM_HOST_ABSENT_SEC` (60 giây) mới chuyển. Chờ 1 phút để rớt mạng chớp nhoáng / tải lại trang không làm mất quyền.

Chủ phòng mới = **người vào phòng sớm nhất còn lại** (LiveKit cho biết giờ vào của từng người). Đổi chủ phòng được ghi vào metadata của phòng → mọi trình duyệt biết ngay và hiện "X hiện là chủ phòng". `meetings.created_by` lấy chủ phòng **lúc kết thúc** → người đó được duyệt đầu việc. Trưởng nhóm luôn điều khiển được, nên kể cả khi chủ phòng cũng chính là trưởng nhóm và bị rớt mạng, phòng không bao giờ rơi vào cảnh không ai điều khiển.

**Tự đóng phòng trống** (`reconcile`, chạy nền mỗi 5 giây trong backend — `room_watcher` ở `main.py`): hỏi LiveKit phòng còn ai không; trống thì ghi `empty_since`, quá `ROOM_EMPTY_CLOSE_SEC` (30 giây) thì đóng. Phòng vừa tạo mà **chưa ai vào được** (`first_joined_at` rỗng — chỉ xảy ra khi lấy vé / kết nối bị lỗi, vì giao diện tạo phòng và vào phòng liền nhau) thì đóng sau `ROOM_UNJOINED_CLOSE_SEC` (1 phút). Dùng cách "hỏi định kỳ" thay cho webhook vì LiveKit chạy trong Docker, gọi ngược về backend trên Windows phải cấu hình mạng thêm; hỏi định kỳ thì không phụ thuộc gì và test được bằng LiveKit giả.

---

## 5. Ghi âm riêng từng người — phần cốt lõi

### Vì sao mỗi người tự ghi mà không để máy chủ ghi?
- LiveKit có dịch vụ ghi (Egress) nhưng là thêm một container nặng (chạy Chrome ẩn).
- Trình duyệt mỗi người vốn đã có tiếng mic của chính họ, **sạch nhất** (trước khi đi qua mạng).
- Dùng lại được bộ ghi âm GĐ3 (MediaRecorder + IndexedDB).

### Máy ghi trong trình duyệt — `hooks/useRoomRecorder.ts`
```
mic (LiveKit) ──► [nút trộn Web Audio] ──► MediaRecorder ──► khúc 3 giây ──► máy chủ
nguồn im lặng ──►        ▲
```
- **Tắt mic** = LiveKit "bịt" đường tiếng (`track.enabled = false`), nút trộn vẫn chạy và ghi ra **khoảng lặng**. File dài đúng bằng thời gian thật → mốc thời gian của mọi người luôn khớp. (Nếu dừng hẳn máy ghi khi tắt mic thì file bị "co lại", mọi câu sau đó lệch giờ.)
- **Đổi mic / bật mic lần đầu**: LiveKit tạo đường tiếng mới → chỉ việc nối nó vào nút trộn, không phải dừng máy ghi.
- "Nguồn im lặng" luôn chạy để lúc chưa có mic máy ghi vẫn nhận dữ liệu liên tục.
- **Mạng chập chờn lúc bắt đầu ghi**: lệnh mở track (`createRoomTrack`) tự thử lại tối đa 5 lần (1s → 10s), tính lại `elapsed_ms` trước mỗi lần thử để không lệch giờ; các khúc ghi được trong lúc chờ được giữ tạm rồi đẩy lên theo đúng thứ tự. Khi dừng ghi, chỉ đóng `TrackUploader` sau sự kiện `onstop` của `MediaRecorder` để không làm rơi khúc cuối. Nếu lỗi quyền hoặc mất mạng quá lâu thì hiện cảnh báo rõ trên thanh thông báo.

### Xếp lời của mọi người lên một trục thời gian
Đồng hồ máy mỗi người lệch nhau vài giây → không dùng được. Cách làm: khi máy ghi vừa chạy, trình duyệt báo máy chủ; **máy chủ đóng dấu giờ theo đồng hồ của nó** (`meeting_tracks.started_at`). Độ lệch của một track = `started_at − recording_started_at của phòng`. Ai vào muộn 40 giây thì mọi câu của họ được cộng 40 giây. Sai số = độ trễ một request trong LAN (vài mili giây).

### Gửi dần từng khúc — `lib/roomTrackUploader.ts` + `append_chunk`
Vì sao không đợi họp xong mới gửi cả file? Vì gửi dần thì họp xong máy chủ **đã có gần đủ**, nhận dạng được ngay; ai đóng tab đột ngột chỉ mất vài giây cuối.

| Vấn đề | Cách xử lý |
|---|---|
| Mất mạng giữa chừng | Khúc nào cũng lưu vào IndexedDB trước; gửi **lần lượt**; lỗi thì thử lại sau 1, 2, 4… 15 giây, không bỏ khúc nào |
| Gửi trùng (request đã tới nơi nhưng trình duyệt không nhận được trả lời) | Mỗi khúc có số thứ tự `seq`. Máy chủ chỉ nối khi `seq == next_seq`; `seq` nhỏ hơn → bỏ qua và trả về bình thường (**idempotent**) |
| Gửi nhảy cóc | Máy chủ trả 409 kèm `expected_seq` → trình duyệt gửi lại từ đúng khúc |
| Hai request cùng ghi một file | `SELECT … FOR UPDATE` khóa dòng track trong lúc nối |
| Đóng tab khi chưa gửi hết | Phần còn lại nằm trong IndexedDB; lần sau mở MeetFlow (hoặc khi có mạng lại) `resumePendingTracks()` gửi nốt |

Các khúc `.webm` nối đuôi nhau theo đúng thứ tự chính là một file `.webm` hợp lệ (khúc đầu chứa phần đầu file) → máy chủ chỉ cần mở file ở chế độ nối thêm. Nếu gói cuối bị cụt (đóng tab đột ngột) khiến Whisper báo lỗi trực tiếp, worker tự giải mã an toàn từng gói sang `.wav` tạm (`audio_mix.transcode_safe_wav`) để cứu phần âm thanh hợp lệ rồi nhận dạng lại. **Đã thử:** file `.webm` bị cắt còn 50% / 80% / 97% đều cứu được trọn phần còn lại. **Chưa cứu được:** file `.m4a` (Safari/iOS) bị cắt cụt — thử với file `.m4a` thường thì hỏng ngay từ bước mở file (phần mục lục của MP4 nằm cuối file), nên phần này ghi vào Hạn chế.

### Kết thúc phòng: chờ ai?
`try_finalize`: đủ mọi track báo "đã gửi xong" → xử lý **ngay**. Còn người chưa xong → chờ tối đa `ROOM_UPLOAD_WAIT_SEC` (120 giây) rồi nhận dạng với phần đã có; trang cuộc họp ghi **"Thiếu ghi âm của …"**.

### Ghi âm đến muộn — `process_late_track_job`
Phần còn lại về sau khi đã nhận dạng:
- Bản ghi **chưa sửa tay và chưa tóm tắt** → tự nhận dạng lại track đó và đưa vào bản ghi.
- Ngược lại → **không tự ghi đè**; hiện nút **"Bổ sung ghi âm của Lan"** cho người duyệt. Khi bấm, chỉ các câu *của track đó* được thay; câu của người khác (kể cả chỗ đã sửa tay) giữ nguyên (`replace_track`).

Lý do: tự sửa một bản ghi người ta đã chỉnh tay / đã dùng để tóm tắt là thay đổi dữ liệu sau lưng người dùng — đúng tinh thần *human-in-the-loop* của GĐ5.

---

## 6. Ghép bản ghi và lọc tiếng vọng — `ai/postprocess/speaker_merge.py`, `workers/online_jobs.py`

Worker nhận dạng **lần lượt từng track** (GPU 4GB chỉ chạy một việc mỗi lúc), đo RMS từng câu theo luồng (`audio_mix.segments_rms`), rồi:
1. `place_segments`: gắn họ tên người nói + cộng độ lệch.
2. Trộn mọi câu theo thời gian.
3. `drop_echoes`: lọc tiếng vọng.
4. Trộn âm thanh của mọi người **theo luồng từng khối 1 giây** thành **một file** `.webm` để nghe lại ở trang cuộc họp (`audio_mix.mix_files`, RAM hằng số chỉ vài MB và có `soft_limit` chống rè tiếng khi nhiều người nói đè nhau).

### Tiếng vọng là gì và lọc thế nào?
Lan nghe bằng loa ngoài → mic của Lan thu lại tiếng Nam → câu của Nam xuất hiện ở **cả hai** track, và bản ở track của Lan bị gán nhầm là "Lan nói". Trình duyệt có khử vọng nhưng không hết. Hai câu bị coi là một câu thu hai lần khi **cả ba** điều kiện đúng:

| Điều kiện | Ngưỡng | Vì sao |
|---|---|---|
| Khác người nói | — | Cùng người thì không phải vọng |
| Cùng thời điểm | bắt đầu lệch ≤ 2 giây, hoặc chồng nhau ≥ 50% | Tiếng vọng tới gần như đồng thời |
| Chữ giống nhau | ≥ 80% (so không dấu; `partial_ratio` vì bản vọng hay cụt đầu / đuôi) | Whisper nghe bản vọng không rõ nên sai vài chữ |

Giữ bản nào? *Mức giọng chuẩn* (`baseline`) của một track = trung vị RMS các câu người đó nói riêng (không nghi vọng). Xét theo thứ tự, để không bị lừa khi mic người này nhạy hơn mic người kia:
1. **Cả hai track có mức giọng chuẩn → so RMS tương đối** (`rms / baseline`). Mic Lan nhạy hơn mic Nam gấp 10 lần thì bản vọng ở track Lan vẫn chỉ bằng ~15% giọng thật của Lan → lọc đúng bản vọng.
2. **Chỉ MỘT track có mức giọng chuẩn → mức tương đối của track đó quyết định.** Hay gặp nhất: người nghe loa ngoài không nói câu nào suốt buổi (không có baseline). Câu của bên có baseline ở mức bình thường của chính nó (> 40%) → bên đó là tiếng thật, bên kia là vọng. **Không** rơi về RMS thô, vì đúng trường hợp này mic người nghe nhạy hơn sẽ làm RMS thô của tiếng vọng to hơn tiếng thật.
3. **Không track nào có mức giọng chuẩn** → RMS thô chỉ được tin khi chênh **rất rõ (≥ 2 lần)**; chênh ít hơn thì tin **thứ tự đến** (tiếng vọng qua WebRTC + loa luôn đến trễ hơn), rồi mới tới RMS thô chênh vừa.
4. **Độ dài câu** (khi không có số đo âm lượng): giữ bản đầy đủ hơn.

Câu ngắn dưới 12 ký tự ("Dạ vâng ạ") **không lọc**: hai người cùng "dạ" một lúc là chuyện thường.

### Vì sao không dùng AI tách người nói (diarization, vd. pyannote — mở rộng E3 cũ)?
Diarization phải **đoán** ai nói từ một file trộn chung: hay nhầm khi nói chen, chỉ ra "Người 1 / Người 2" chứ không biết tên, và tốn thêm VRAM. Ở đây mỗi người đăng nhập bằng tài khoản và ghi bằng mic của mình → "ai nói" là **dữ kiện có sẵn**, không phải kết quả suy đoán. Diarization vẫn có ích cho cuộc họp tải từ file — để ở hướng phát triển.

---

## 7. Dùng tên người nói để giao việc — `ai/extraction.py`, `ai/llm/prompts.py`

GĐ4 gặp "để em làm" phải **để trống** người làm vì bản ghi không cho biết ai nói. Giờ bản ghi đưa cho LLM có dạng:
```
Nguyễn Văn Nam: Ai nhận phần slide thuyết trình?
Trần Thị Lan: Dạ phần slide để em làm ạ.
```
Prompt thêm quy tắc: người nói **tự nhận** việc → ghi tên người nói ở đầu dòng thay cho đại từ; người nói **giao cho người khác** bằng đại từ ("em làm phần này nhé") mà không rõ là ai → vẫn ghi đại từ, **không gán cho người nói**.

Phần quyết định cuối cùng vẫn là **code**, không phải LLM (giữ nguyên tắc GĐ4):

| Tình huống | Kết quả |
|---|---|
| Người làm (sau khi ghép tên) **chính là người nói** câu bằng chứng | Kiểu ghép `speaker` — "người nói tự nhận", điểm 100 |
| Nhóm có 2 bạn trùng tên, một trong hai là người nói câu đó | Chọn đúng người nói (GĐ4 phải báo "trùng nhiều thành viên") |
| LLM vẫn trả về đại từ | Giữ `self`, để trống cho người duyệt chọn. Không đoán: "em làm nhé" (giao) và "em làm ạ" (nhận) khác nhau ở ngữ cảnh, luật cứng không phân biệt được |
| LLM chép gộp lời của **2 người** làm câu bằng chứng (*"Phần slide thì ai nhận? Để em làm ạ."*) | **Không dùng nhãn người nói** cho việc đó (`quote_speakers`): từng câu riêng đều khớp một phần 100% nên không biết chắc câu bằng chứng là của ai. Ghép cặp 2 câu liền nhau (khi Whisper cắt đôi một câu) cũng chỉ ghép khi **cùng người nói** |
| Gộp việc trùng (`_dedupe`) | So người làm theo `assignee_id` trước (thay vì chuỗi chữ), nên câu tự nhận ("Nguyễn Văn Nam") và câu chốt cuối buổi ("Nam") được gộp thành 1 việc, giữ nhãn `speaker` |

Tham số `use_speakers=False` của `extract_meeting` bỏ tên người nói khỏi các dòng → dùng cho **thí nghiệm có / không có nhãn người nói** ở GĐ7.

---

## 8. API mới

| Phương thức | Đường dẫn | Việc |
|---|---|---|
| GET / POST | `/api/workspaces/{id}/room` | Phòng đang mở của nhóm / mở phòng (có rồi thì trả về phòng đó) |
| GET | `/api/rooms/{code}` | Thông tin phòng qua link |
| POST | `/api/rooms/{code}/join` | Lấy vé LiveKit (tự vào nhóm nếu chưa ở trong) |
| POST | `/api/rooms/{code}/recording/start` · `/stop` | Bắt đầu / dừng ghi (chủ phòng, trưởng nhóm) |
| POST | `/api/rooms/{code}/leave` | "Chỉ mình tôi rời": chủ phòng rời thì nhượng quyền ngay (không còn ai thì kết thúc) |
| POST | `/api/rooms/{code}/end` | Kết thúc cho mọi người |
| POST | `/api/rooms/{code}/tracks` | Trình duyệt mở track ghi âm của mình |
| PUT | `/api/room-tracks/{id}/chunks/{seq}` | Gửi một khúc (dữ liệu thô) |
| POST | `/api/room-tracks/{id}/finish` | Báo đã gửi hết |
| POST | `/api/meetings/{id}/tracks/{track_id}/merge` | Người duyệt bấm "Bổ sung ghi âm của …" |

---

## 9. Kiểm thử

**192 test tự động** (25 test trong `tests/test_rooms.py`, 9 test trong `tests/test_audio_mix.py`, test bổ sung ở `tests/test_llm.py`, 12 test cho bộ khung thực nghiệm trong `tests/test_experiments.py`). LiveKit, Whisper, LLM đều thay bằng bản giả → không cần LiveKit / GPU:

| Nhóm | Kiểm tra |
|---|---|
| Phòng | Một phòng mở mỗi nhóm; vé LiveKit đúng nội dung; link phòng tự thêm người ngoài vào nhóm; đủ 6 người thì chặn; LiveKit tắt thì báo rõ và không để lại phòng "ma" |
| Ghi âm | Chỉ chủ phòng / trưởng nhóm điều khiển; ghi một mạch; không ghi âm thì không tạo cuộc họp |
| Chủ phòng | Chủ phòng rời → quyền sang người vào sớm nhất, chủ phòng cũ mất nút, trưởng nhóm vẫn còn; người cuối cùng rời → phòng kết thúc; vắng 40 giây chưa đổi, vào lại kịp thì giữ quyền, quá 1 phút mới đổi; phòng tạo ra mà không ai vào được thì đóng sau 1 phút |
| Gửi khúc | Đúng thứ tự, gửi trùng không nối hai lần, nhảy cóc bị từ chối, không ghi được vào track của người khác |
| Kết thúc | Chờ người chưa gửi xong; người cuối gửi xong thì xử lý ngay; hết 2 phút thì thôi chờ; phòng trống tự đóng |
| Bản ghi | Có tên người nói, người vào muộn được dời mốc, sửa chữ không mất tên người nói, không ai nói thì báo lỗi rõ |
| Đến muộn | Tự bổ sung khi bản ghi chưa đụng tới; đã sửa tay thì chờ người duyệt bấm; chỗ sửa tay của người khác vẫn còn |
| Tiếng vọng | Bỏ bản vọng, giữ người nói thật (kể cả khi mic người nghe nhạy hơn mic người nói gấp 10 lần, hoặc người nghe không nói câu nào suốt buổi); không bỏ nhầm câu ngắn, câu khác nội dung, câu cách xa nhau |
| Âm thanh | Trộn và đo RMS theo luồng từ file `.webm` thật; `soft_limit` chống cắt phẳng khi 6 người nói đè nhau; tự cứu file `.webm` bị cụt đuôi sang `.wav` tạm để nhận dạng |
| Giao việc | Người nói tự nhận → đúng tài khoản dù trùng tên; đại từ giao cho người khác → không gán bừa; không ghép câu trích dẫn xuyên qua 2 người nói; gộp việc trùng theo `assignee_id`; tắt nhãn thì như GĐ4 |

**Thử đầu-cuối bằng âm thanh thật (18/11/2026)** — API thật + LiveKit thật + Whisper trên GPU + Gemini, trên CSDL test. Cuộc họp mẫu 85 giây được tách thành 3 file riêng (Nam, Lan, Minh); Minh "vào muộn" 10 giây; track của Lan bị trộn thêm tiếng Nam nhỏ 12% và trễ 0,3 giây (giả lập nghe loa ngoài):

| Chỉ số | Kết quả |
|---|---|
| Câu được gán đúng người nói | **19 / 19** |
| Mốc thời gian của người vào muộn | Câu đầu của Minh: 38,1 giây (đúng ra 38,0) |
| Câu tiếng vọng bị lọc | **12** (toàn bộ lời Nam lọt vào track của Lan), không bỏ nhầm câu nào |
| Thời gian nhận dạng 3 track | 18,4 giây cho 85 giây họp |
| Đầu việc | 4 / 4, đúng người, đúng hạn, câu gốc tìm thấy 4 / 4 |
| "Còn phần anh, anh sẽ chuẩn bị bộ dữ liệu…" | Giao cho **Nguyễn Văn Nam** (GĐ4 phải để trống người làm) |

> Giọng máy đọc, tiếng vọng giả lập bằng cách trộn file → đây là **cận trên**, giống các kết quả GĐ3–4. Số liệu với người thật để ở GĐ7.

**Thử trên trình duyệt (18/11/2026, tài khoản test Lan, `http://localhost:5173`):** nút "📹 Online Meeting" mở phòng → màn hình chờ → vào phòng, kết nối LiveKit thật qua `/rtc` (239 ms) → danh sách người tham gia có nhãn "Chủ phòng" → bấm "Bắt đầu ghi": hiện chấm đỏ + dòng báo ghi âm, trình duyệt mở track và gửi 6 khúc → "Kết thúc cho mọi người": bị mời ra, khúc cuối vẫn được gửi nốt, cuộc họp nguồn "Online Meeting" xuất hiện → worker thật xử lý và báo đúng *"Không nhận ra lời nói… (mic của mọi người đều tắt)"*.
Chế độ LAN: `npm run dev:lan` phục vụ `https://192.168.1.100:5174` bằng chứng chỉ tự ký, `/api` và `/rtc` đều chuyển tiếp đúng.

## 10. CHƯA thử được — cần người làm khóa luận tự thử

Khung trình duyệt của công cụ lập trình **chặn mic / cam** và chỉ có một máy, nên các điểm sau chưa được kiểm chứng bằng thực tế:

1. **Hai thiết bị thật trong cùng Wi-Fi** vào `https://<IP>:5173`: chấp nhận chứng chỉ, thấy và nghe nhau (liên quan tường lửa Windows + cổng UDP 7882 của Docker).
2. **Mic thật**: nói vài câu → bản ghi ra đúng tên người nói. (Đường xử lý sau khi âm thanh tới máy chủ đã thử bằng file thật; phần chưa thử là trình duyệt thu mic thật qua nút trộn.)
3. **Tắt / bật mic giữa chừng, đổi mic** khi đang ghi → mốc thời gian vẫn khớp.
4. **Camera, chia sẻ màn hình**, giao diện trên điện thoại.
5. **Tiếng vọng thật** (một người nghe loa ngoài) và ngưỡng 80% / 2 giây có hợp không.
6. **Rớt mạng / đóng tab** giữa buổi rồi mở lại → ghi âm được gửi nốt và bổ sung.

## 11. Hạn chế (nói thật khi bảo vệ)

- Chỉ chạy trong LAN. Người ở xa cần máy chủ có IP công khai (hoặc LiveKit Cloud + Cloudflare Tunnel) — hướng phát triển.
- Lọc tiếng vọng dựa trên chữ Whisper nghe được: bản vọng bị nghe sai quá nhiều (dưới 80%) sẽ lọt.
- Người nghe loa ngoài mà nói *chen* đúng lúc người khác nói: hai giọng lẫn trong một track, Whisper có thể ghép thành một câu sai.
- Một người dùng hai thiết bị cùng tài khoản: LiveKit coi là một người (thiết bị vào sau đẩy thiết bị trước ra).
- Lọc tiếng vọng khi **không ai có mức giọng chuẩn** (mọi câu đều bị vọng) **và** mic lệch độ nhạy ≥ 2 lần **và** mốc thời gian Whisper của hai bản gần như trùng nhau: không còn căn cứ nào chắc chắn, có thể giữ nhầm bản.
- File nghe lại trộn theo luồng nên không tốn RAM theo độ dài buổi họp, nhưng **bước nhận dạng vẫn nạp nguyên ghi âm của từng người** vào RAM (faster-whisper giải mã cả file): khoảng 230 MB cho track dài 1 giờ, xử lý lần lượt từng người.
- File `.m4a` (Safari/iOS) bị cụt đuôi chưa cứu được (xem mục 5); `.webm` (Chrome / Edge / Firefox) thì cứu được.

## 12. Cải thiện & sửa lỗi logic trước GĐ7 (19/11/2026)

Trước khi chạy thực nghiệm với người thật ở GĐ7, rà soát lại code GĐ4–GĐ6 phát hiện **5 điểm yếu logic / kỹ thuật** và đã sửa (xem thêm phần *Rà soát lại* ngay dưới bảng — 3 trong 5 bản sửa được chỉnh tiếp):

| # | Lỗi / hạn chế ở bản cũ | Vì sao dễ hỏng khi chạy thật | Đã sửa như thế nào | File sửa |
|---|---|---|---|---|
| 1 | `_dedupe` so trùng người làm theo chuỗi chữ `raw_assignee` | Trong Online Meeting, lúc tự nhận LLM ghi `"Nguyễn Văn Nam"`, cuối buổi người khác chốt ghi `"Nam"` → cùng một người nhưng khác chữ nên **không gộp được, tạo 2 đầu việc trùng** | Thêm `_assignee_key`: ưu tiên so theo `assignee_id` nếu đã ghép tài khoản; chưa có tài khoản thì bỏ xưng hô (`strip_honorific`) rồi mới so. Khi gộp vẫn giữ nhãn `speaker` và không ghi đè câu gốc hợp lệ | `backend/app/ai/extraction.py` |
| 2 | `find_evidence` ghép 2 câu liền nhau mà không kiểm tra người nói | Nếu câu `i` của Nam (*"Ai làm slide?"*) và câu `i+1` của Lan (*"Để em làm ạ"*) bị ghép cặp, hàm trả vị trí câu `i` → **gán nhầm `said_by` sang Nam** | Chỉ cho phép ghép cặp câu `i` và `i+1` khi **cùng `speaker_id` và `speaker`** (bản ghi thường không có nhãn vẫn ghép như cũ) | `backend/app/ai/extraction.py` |
| 3 | `drop_echoes` so trực tiếp RMS thô giữa 2 mic khác nhau | Mic của người bật loa ngoài có thể nhạy hơn mic người nói thật → tiếng vọng có RMS thô **to hơn** giọng gốc → **lọc nhầm câu thật, giữ câu vọng** | Tính *mức giọng chuẩn* (`baseline`, trung vị RMS) của từng track chỉ trên các câu nói riêng không nghi vọng, rồi so **RMS tương đối** (`rms / baseline`); rơi về RMS thô khi thiếu baseline (VD. người chỉ nghe không nói), sau đó xét độ trễ thời gian (vọng đến sau) và độ dài câu | `backend/app/ai/postprocess/speaker_merge.py` |
| 4 | Khởi tạo track không retry, `elapsed_ms` luôn bằng 0, dễ rơi khúc cuối & chưa cứu file cụt đuôi / `.m4a` | Mạng chập chờn đúng lúc bấm ghi làm máy ghi tắt im lặng (`idle`) → mất cả track; `rec.stop()` chạy đúng lúc `createRoomTrack` vừa trả về có thể đóng uploader trước khi khúc cuối kịp vào; đóng tab đột ngột / Safari `.m4a` dễ làm file lỗi cuối | `useRoomRecorder` retry tối đa 5 lần (1s → 10s), tính lại `elapsed_ms` ngay trước mỗi lần gọi, lỗi cứng chuyển `'error'` để hiện cảnh báo rõ, chỉ đóng uploader sau `rec.onstop`. Worker thêm `transcode_safe_wav` tự cứu file cụt đuôi / `.m4a` sang `.wav` tạm khi STT lỗi trực tiếp | `frontend/src/hooks/useRoomRecorder.ts`, `frontend/src/pages/RoomPage.tsx`, `backend/app/workers/online_jobs.py` |
| 5 | Trộn file nghe lại giữ nguyên mảng `float32` cả buổi trong RAM (~230 MB/giờ) và `np.clip` cứng | Họp dài 3–4 tiếng ngốn nhiều trăm MB RAM; 2–6 người nói đè nhau cộng biên độ vượt `1.0` bị cắt phẳng gây rè tiếng | Chuyển `segments_rms` và `mix_files` sang **đọc / trộn theo luồng từng khối 1 giây** qua PyAV (RAM hằng số chỉ vài MB bất kể thời lượng) và nén biên độ mượt bằng `soft_limit` (giữ nguyên dưới `0,75`, nén hữu tỉ về dưới `0,98`) | `backend/app/ai/audio_mix.py`, `backend/app/workers/online_jobs.py` |


### Rà soát lại các bản sửa (19/11/2026)

Kiểm lại từng bản sửa bằng cách chạy thử (không chỉ đọc code) thì thấy 3 chỗ chưa đạt đúng điều tài liệu mô tả, đã sửa tiếp:

| Bản sửa | Phát hiện khi chạy thử | Đã sửa tiếp |
|---|---|---|
| 2 — ghép câu trích dẫn | Chưa chặn được đúng tình huống nhắm tới. `find_evidence` so khớp **một phần**, nên khi LLM chép gộp *"Phần slide thì ai nhận? Để em làm ạ."*, câu hỏi của Nam riêng đã khớp 100% → vẫn trả về câu của Nam (bước ghép cặp không được dùng tới) → việc bị gắn nhãn "người nói tự nhận" cho Nam | Thêm `quote_speakers`: câu bằng chứng chứa trọn câu của **từ 2 người nói trở lên** → không dùng nhãn người nói, chỉ ghép tên như GĐ4 (không chắc thì không đoán). Test `test_cross_speaker_quote_is_not_labelled_self_claim` |
| 3 — lọc tiếng vọng | Đúng khi mic nhạy gấp 10 lần **hoặc** người nghe không nói; nhưng **cả hai cùng lúc** (mô phỏng 4 câu) thì bỏ nhầm **4/4 câu thật** của Nam, giữ tiếng vọng như thể Lan nói. Nguyên nhân: chỉ một bên có mức giọng chuẩn thì code không kết luận gì mà rơi về RMS thô — đúng cái dễ bị mic nhạy đánh lừa | Tầng 2 mới: chỉ một bên có mức giọng chuẩn thì mức tương đối của bên đó quyết định; không ai có mức giọng chuẩn thì RMS thô phải chênh ≥ 2 lần mới thắng thứ tự đến. Sau sửa: 0/4 câu bị bỏ nhầm ở mọi kịch bản đã thử. Test `test_echo_filter_silent_listener_with_sensitive_mic_keeps_real_speaker`, `test_echo_filter_without_any_baseline_prefers_arrival_order` |
| 4 — cứu file cụt đuôi | (a) Code bắt lỗi bằng `av.AVError`, nhưng PyAV 15 (bản đang dùng) **không còn lớp này** (đổi tên thành `av.FFmpegError`) → gặp gói lỗi giữa chừng thì văng `AttributeError` thay vì "dừng êm, giữ phần đã đọc". Lỗi ẩn vì `.webm` cụt không làm PyAV báo lỗi. (b) Tài liệu ghi cứu được `.m4a` nhưng thử thì không mở được | (a) Dùng `_av_errors()` (nhận cả tên cũ lẫn tên mới). Test `test_decode_error_mid_stream_keeps_audio_read_so_far` giả lập gói hỏng giữa file. (b) Sửa tài liệu, đưa `.m4a` cụt vào Hạn chế |
| 5 — trộn theo luồng | Đúng, nhưng tài liệu xóa luôn dòng hạn chế về RAM trong khi bước nhận dạng vẫn nạp cả track | Ghi lại đúng phạm vi vào Hạn chế |

---

## Hội đồng hỏi thì trả lời

- **"Sao không dùng Google Meet rồi tải ghi âm lên?"** Vẫn được — tải file là nguồn thứ nhất. Họp trong app thêm được thứ Meet không cho: *ai nói câu nào* gắn với đúng tài khoản trong nhóm, nên việc "để em làm" được giao tự động.
- **"Em tự viết gọi video à?"** Không. Phần truyền hình / tiếng dùng LiveKit (mã nguồn mở). Phần em làm: cấp quyền vào phòng, vòng đời phòng, ghi âm theo người với mốc thời gian chung, gửi từng khúc chịu được rớt mạng, ghép bản ghi, lọc tiếng vọng, giao việc cho người nói.
- **"Ghi âm có xin phép không?"** Chỉ chủ phòng / trưởng nhóm bật được; mọi người thấy chấm đỏ và dòng thông báo; người vào sau được báo ngay ở màn hình chờ; tắt mic thì không ghi. Ghi âm lưu trên máy chủ của nhóm, Whisper chạy tại chỗ.
- **"Đồng hồ các máy lệch nhau thì sao?"** Không dùng đồng hồ của trình duyệt; máy chủ đóng dấu giờ khi mỗi máy ghi bắt đầu.
- **"Chủ phòng rớt mạng thì ai tắt được phòng?"** Trưởng nhóm luôn tắt được. Ngoài ra chủ phòng vắng quá 1 phút thì quyền tự chuyển cho người vào sớm nhất còn lại; mọi người rời hết thì phòng tự đóng sau 30 giây.
- **"Một người rớt mạng thì cả nhóm phải chờ?"** Chờ tối đa 2 phút, sau đó xử lý với phần đã có và ghi rõ thiếu của ai; phần về muộn được bổ sung.

## Tự kiểm tra

1. SFU là gì? Vì sao 6 người họp cần SFU thay vì gửi thẳng cho nhau?
2. Vì sao máy khác trong LAN phải mở bằng `https://`? Chứng chỉ tự ký khác chứng chỉ thật ở đâu?
3. Vé vào phòng chứa gì? Vì sao LiveKit tin vé mà không cần hỏi backend?
4. Vì sao web, API và LiveKit đi chung một địa chỉ `:5173`? Thứ gì KHÔNG đi qua địa chỉ đó?
5. Ràng buộc "mỗi nhóm một phòng mở" được bảo đảm ở đâu? Vì sao kiểm tra bằng code thôi là chưa đủ?
6. Vì sao mỗi người tự ghi mic của mình thay vì máy chủ ghi?
7. Tắt mic thì file ghi âm của người đó ra sao? Nếu dừng hẳn máy ghi thì hỏng chỗ nào?
8. Lời của người vào muộn được xếp đúng thứ tự bằng cách nào?
9. Gửi khúc bị lặp / nhảy cóc / mất mạng được xử lý thế nào? "Idempotent" nghĩa là gì?
10. Phòng kết thúc mà còn người chưa gửi xong ghi âm thì hệ thống làm gì? Phần về muộn đi đâu?
11. Vì sao ghi âm đến muộn không tự chèn vào bản ghi đã sửa tay?
12. Ba điều kiện để hai câu bị coi là tiếng vọng? Giữ bản nào, dựa vào đâu? Vì sao không so thẳng âm lượng của hai mic? Nếu người nghe loa ngoài không nói câu nào thì sao?
13. Vì sao không dùng diarization (pyannote)?
14. "Để em làm ạ" và "Em làm phần này nhé" được xử lý khác nhau thế nào? Ai quyết định: LLM hay code?
15. Những gì trong giai đoạn này CHƯA được thử bằng thực tế?
