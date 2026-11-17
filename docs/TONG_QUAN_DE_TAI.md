# TỔNG QUAN ĐỀ TÀI

**Tên đề tài:** Nghiên cứu và xây dựng hệ thống quản lý công việc nhóm tích hợp AI tự động tóm tắt cuộc họp và tạo đầu việc

**Tên sản phẩm:** MeetFlow

---

## 1. Vấn đề cần giải quyết

Sau mỗi buổi họp nhóm / họp công ty thường xảy ra:
- **Mọi người quên mất mình phải làm gì**, hạn chót là khi nào.
- **Tốn thời gian viết biên bản**: phải có người vừa họp vừa ghi chép, rồi ngồi gõ lại.
- **Không ai theo dõi tiến độ**: giao việc bằng lời trong cuộc họp, xong rồi trôi mất, đến hạn mới biết chưa ai làm.

## 2. Công dụng

> **Biến một file ghi âm cuộc họp thành danh sách công việc có người chịu trách nhiệm, có hạn chót, được nhắc nhở và theo dõi tiến độ.**

- **Tiết kiệm thời gian:** không cần người ghi biên bản; AI nghe, tóm tắt và tách đầu việc.
- **Không bỏ sót việc:** mọi việc được giao trong cuộc họp đều lên bảng công việc.
- **Rõ trách nhiệm:** mỗi việc gắn với **một người** và **một hạn chót**.
- **Khép kín vòng theo dõi:** người được giao nhận thông báo và được nhắc khi sắp hạn; người giao việc biết khi việc hoàn thành.

### Khác gì so với dán bản ghi vào ChatGPT?
| ChatGPT / công cụ tóm tắt | MeetFlow |
|---|---|
| Dừng ở **bản tóm tắt** dạng văn bản | Biến tóm tắt thành **công việc thật** trên bảng Kanban |
| Không biết ai là ai trong nhóm | Ghép tên trong cuộc họp với **thành viên nhóm** (qua biệt danh) |
| Không nhắc hạn, không theo dõi | **Thông báo**, nhắc hạn, theo dõi tiến độ, tổng kết hằng ngày |
| Phải tự copy, tự gửi cho từng người | Mỗi người tự thấy **"Việc của tôi"**; có email / tin nhắn Zalo soạn sẵn |
| Gửi ghi âm lên dịch vụ bên ngoài | Nhận dạng giọng nói **chạy ngay trên máy** (GPU), có thể chạy offline |

## 3. Đối tượng sử dụng

- **Nhóm sinh viên** làm đồ án, khóa luận.
- **Nhóm làm việc nhỏ** trong công ty, startup, câu lạc bộ.
- **Trưởng nhóm / quản lý** cần theo dõi ai đang làm gì.

Chỉ **người tổ chức cuộc họp** bắt buộc có tài khoản; thành viên khác có thể tham gia sau.

## 4. Luồng sử dụng chính

```
 1. Họp xong, tải file ghi âm lên        🎙️  (hoặc dán biên bản có sẵn)
            │
 2. AI chuyển giọng nói → văn bản        🧠  Whisper, chạy trên GPU
            │
 3. Người dùng nghe lại, sửa chỗ sai     ✏️  (tên người, ngày tháng)
            │
 4. AI tóm tắt cuộc họp + tách đầu việc  ✨  Ai làm – Làm gì – Hạn chót
            │
 5. Người dùng duyệt, bấm "Đẩy lên bảng" ✅  con người kiểm soát kết quả AI
            │
 6. Công việc lên bảng Kanban            📋  Cần làm / Đang làm / Hoàn thành
            │
 7. Mọi người nhận thông báo, làm việc   🔔  nhắc hạn, theo dõi tiến độ
```

**Ví dụ:** cuộc họp có câu *"Lan viết chương hai, nộp trước thứ Sáu tuần này nhé"* → hệ thống tạo thẻ **"Viết chương 2"**, giao cho **Lan**, hạn **20/11/2026**, Lan nhận thông báo và được nhắc khi sắp đến hạn.

---

## 5. Chức năng

Ký hiệu: ✅ đã làm xong · 🔜 đang / sắp làm · 💡 mở rộng nếu còn thời gian

### 5.1. Phân hệ quản lý công việc nhóm
| Mã | Chức năng | Trạng thái |
|---|---|---|
| F01 | Đăng ký, đăng nhập (mật khẩu băm bcrypt, JWT) | ✅ |
| F02 | Hồ sơ cá nhân | ✅ |
| F03 | Tạo nhóm, mời thành viên bằng link / email, phân quyền trưởng nhóm – thành viên, **biệt danh** thành viên | ✅ |
| F04 | Nhiều bảng công việc mỗi nhóm, cột tùy chỉnh (mặc định Cần làm / Đang làm / Hoàn thành) | ✅ |
| F05 | Thẻ công việc: người làm, hạn chót, mức ưu tiên, mô tả, bình luận | ✅ |
| F06 | **Kéo-thả** thẻ giữa các cột, **cập nhật realtime** cho mọi thành viên | ✅ |
| F07 | Lọc / tìm kiếm, trang **"Việc của tôi"** | ✅ |
| F08 | Thông báo: được giao việc, sắp đến hạn, quá hạn | ✅ |

### 5.2. Phân hệ AI cuộc họp (trọng tâm)
| Mã | Chức năng | Trạng thái |
|---|---|---|
| F09 | Tạo cuộc họp (tên, ngày họp) | ✅ |
| F10 | Tải file ghi âm (mp3, m4a, wav…), file .txt, dán văn bản, hoặc **ghi âm trực tiếp** | ✅ |
| F11 | **Chuyển giọng nói → văn bản** trên GPU, thanh tiến độ realtime, tách theo từng câu, **lọc "ảo giác" của AI** | ✅ |
| F12 | Nghe lại audio đồng bộ với bản ghi, **sửa bản ghi** | ✅ |
| F13 | **Tóm tắt cuộc họp**: chủ đề, ý chính, quyết định, vấn đề còn mở | ✅ |
| F14 | **Trích xuất đầu việc**: Ai làm – Làm gì – Hạn chót, kèm trích dẫn câu gốc (**được kiểm tra lại bằng code**) | ✅ |
| F15 | Ghép tên trong cuộc họp với tài khoản thành viên (qua biệt danh, so khớp mờ) | ✅ |
| F16 | Đổi ngày tương đối ("thứ Sáu tuần sau") thành ngày cụ thể, tính theo ngày họp | ✅ |
| F17 | **Màn hình duyệt** + nút **"Đẩy lên bảng"** | 🔜 Giai đoạn 5 |
| F18 | Lịch sử cuộc họp, truy vết thẻ được tạo từ cuộc họp nào | 🔜 Giai đoạn 5 |
| F19 | Xuất biên bản PDF / Word | 🔜 Giai đoạn 5 |

### 5.3. Thông báo & mời thành viên (đã chốt bổ sung)
| Mã | Chức năng | Trạng thái |
|---|---|---|
| F20 | Giao việc theo **tên** khi người đó chưa có tài khoản | 🔜 |
| F21 | **Tự nhận tên**: tên AI nghe được mà chưa khớp tài khoản (kể cả biệt danh) hiện thành danh sách; người đó vào nhóm và **bấm nhận tên của mình** để nhận việc. Trưởng nhóm được báo và có thể hoàn tác | 🔜 |
| F22 | Nút **"Sao chép tin nhắn"** kết quả cuộc họp để dán vào Zalo / Messenger | 🔜 |
| F23 | **Email** báo việc mới (mỗi người chỉ nhận việc của mình) | 🔜 |
| F24 | Thông báo **"Duy đã hoàn thành…"** cho người giao việc | 🔜 |
| F25 | **Email tổng kết cuối ngày** cho trưởng nhóm (xong / đang làm / trễ hạn) | 🔜 |

### 5.4. Mở rộng
| Mã | Chức năng | |
|---|---|---|
| E1 | **Ghi âm trực tiếp trên trình duyệt**, lưu tạm trên máy, tự tải lên khi có mạng lại | ✅ |
| E2 | Hỏi đáp lịch sử cuộc họp (VD: *"Tháng trước nhóm chốt dùng database gì?"*) | 💡 |
| E3 | Tách người nói (ai nói câu nào) | 💡 |
| E4 | Dashboard thống kê khối lượng công việc | 💡 |
| E5 | **Voice note giao việc nhanh**: bấm micro nói 1 câu → thẻ lên bảng | 💡 |

---

## 6. Công nghệ

| Thành phần | Công nghệ |
|---|---|
| Giao diện | React + TypeScript + Vite + TailwindCSS, kéo-thả dnd-kit |
| Máy chủ | FastAPI (Python) |
| Cơ sở dữ liệu | PostgreSQL |
| Hàng đợi xử lý nền | Redis + RQ (worker AI chạy riêng, xử lý lần lượt) |
| Realtime | WebSocket + Redis Pub/Sub |
| Nhận dạng giọng nói | **faster-whisper** (`large-v3-turbo`, lượng tử hóa int8), chạy trên GPU của máy |
| Tóm tắt & trích xuất | **Gemini API** (`gemini-3.5-flash`, tự chuyển sang `gemini-3.5-flash-lite` khi quá tải), Qwen qua Ollama (chạy trên máy, để so sánh — đã viết code, chưa chạy với mô hình thật) |
| Hạ tầng | Docker (PostgreSQL + Redis) |

## 7. Kết quả đạt được tới hiện tại (đo thật trên laptop RTX 3050 4GB)

| Chỉ số | Kết quả |
|---|---|
| Tốc độ nhận dạng | Cuộc họp 85 giây xử lý trong **3,6 giây** (nhanh gấp **23 lần** thời gian thực) |
| Độ chính xác (WER, tiếng Việt) | **2,09%** lỗi từ (đúng 234/239 từ) |
| Nhận đúng tên thành viên | "Nam" trước bị nghe thành "NOM" → nhờ gợi ý tên thành viên, giờ nghe đúng |
| Chống AI bịa chữ | Chặn được các câu ảo giác kiểu *"Hãy subscribe cho kênh…"*; file nhạc / không có lời nói được báo lỗi rõ ràng |
| Trích xuất đầu việc (cuộc họp mẫu, Gemini) | **4/4 đầu việc**, đúng hạn chót 4/4, câu gốc tìm thấy 4/4; 1 việc người nói tự nhận được cố ý để trống người làm |
| Thời gian tóm tắt | Khoảng **11–19 giây** cho cuộc họp 85 giây |
| Kiểm thử tự động | 129 test |

## 8. Điểm nhấn khi bảo vệ

1. **Giải quyết trọn vòng**, không chỉ tóm tắt: ghi âm → công việc → thông báo → theo dõi tiến độ.
2. **Có phần nghiên cứu thật:** đo WER, so sánh mô hình nhận dạng giọng nói và các LLM khi trích xuất đầu việc.
3. **Cải tiến dựa trên ngữ cảnh hệ thống:** dùng danh sách thành viên và biệt danh để AI nhận đúng tên người.
4. **Kiểm soát rủi ro của AI:** lọc ảo giác, trích dẫn câu gốc, **con người duyệt** trước khi tạo công việc.
5. **Bảo mật dữ liệu cuộc họp:** nhận dạng giọng nói chạy ngay trên máy, có thể chạy hoàn toàn offline.

---

*Chi tiết kỹ thuật từng phần: xem các file `docs/GIAI_THICH_GIAI_DOAN_*.md`. Kế hoạch và lộ trình: `docs/KE_HOACH_PHUONG_AN_B.md`.*
