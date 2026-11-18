# KHẢO SÁT SẢN PHẨM TƯƠNG TỰ (Chương 1)

**Mục đích:** chỉ ra đề tài nằm ở đâu so với các sản phẩm đã có, và trả lời câu hỏi chắc chắn gặp khi bảo vệ: *"Đã có Otter, Fireflies, Jira… rồi, em làm khác gì?"*

**Cách khảo sát (nói thật trong báo cáo):**
- Thông tin lấy từ **trang chính thức** của từng sản phẩm, truy cập ngày **18/11/2026**. Chỗ nào chỉ có nguồn bên thứ ba thì ghi rõ.
- Riêng **Meetily** và **LiveKit Meet** được đọc trực tiếp từ mã nguồn tải về (`tham_khao/`, bản ngày 14/11 và 17/11/2026).
- **Chưa dùng thử trực tiếp** sản phẩm nào ngoài MeetFlow. Trước khi đưa vào báo cáo cần tự dùng thử, chụp màn hình và kiểm tra lại (mục 6).
- Các sản phẩm này cập nhật rất nhanh (ví dụ Otter mới thêm tiếng Việt trong tháng 11/2026) → luôn ghi **ngày truy cập** cạnh mỗi nhận định.

Ký hiệu: ✅ có · ◐ có một phần / có điều kiện · ❌ không · **?** không thấy công bố trên trang đã xem

---

## 1. Ba nhóm sản phẩm

| Nhóm | Đại diện | Làm tốt | Dừng lại ở đâu |
|---|---|---|---|
| **A. Trợ lý ghi chép cuộc họp** | Otter.ai, Fireflies.ai, Google Meet (Gemini), Meeting.ai, Meetily | Ghi âm, chuyển thành văn bản, tóm tắt | Biên bản và danh sách việc cần làm dạng *văn bản*; muốn theo dõi tiến độ phải đẩy sang công cụ khác |
| **B. Quản lý công việc** | Trello, Jira, Notion | Bảng Kanban, giao việc, hạn chót, theo dõi | Gốc là công cụ quản lý việc; phần cuộc họp là tính năng thêm vào sau, thường cần gói trả phí hoặc ghép nhiều sản phẩm |
| **C. Hạ tầng họp trực tuyến** | LiveKit Meet (mã nguồn mở) | Gọi video nhiều người | Không có AI, không có quản lý công việc |

**MeetFlow** nằm ở giao của A và B: một hệ thống duy nhất đi từ *ghi âm* tới *thẻ công việc có người làm, có hạn, được theo dõi*.

---

## 2. Nhóm A — trợ lý ghi chép cuộc họp

| Tiêu chí | Otter.ai | Fireflies.ai | Google Meet (Gemini) | Meeting.ai | Meetily | **MeetFlow** |
|---|---|---|---|---|---|---|
| Hình thức | Dịch vụ đám mây | Dịch vụ đám mây | Tính năng trong Google Meet | Dịch vụ đám mây | Ứng dụng cài trên máy, mã nguồn mở (MIT) | Web tự triển khai (đề tài) |
| Lấy nội dung họp | Bot tự vào Zoom / Teams / Meet | Bot vào cuộc họp | Ngay trong cuộc họp Meet | Bot vào cuộc gọi; ghi trực tiếp; tải file | Ghi âm thanh trên máy; nhập file | Tải file · ghi trực tiếp · dán văn bản · **phòng họp riêng** (LAN). ❌ không có bot vào Zoom / Meet |
| Nhận dạng **tiếng Việt** | ✅ từ tháng 11/2026 | ✅ (100+ ngôn ngữ) | ❌ ghi chú tự động chỉ 8 ngôn ngữ, chưa có tiếng Việt | **?** | ◐ dùng Whisper (đa ngôn ngữ), README không nêu riêng tiếng Việt | ✅ WER 2,09% trên mẫu giọng máy đọc |
| Âm thanh xử lý ở đâu | Máy chủ nhà cung cấp | Máy chủ nhà cung cấp | Máy chủ Google | Máy chủ nhà cung cấp | ✅ **trên máy người dùng** | ✅ **trên máy của nhóm** (faster-whisper, GPU) |
| Biết ai nói câu nào | ✅ nhận diện giọng | ✅ nhận diện giọng | **?** | ✅ "Voice Match" | ◐ chỉ bản PRO trả phí (10 USD / người / tháng) | ✅ **chắc chắn** với phòng Online Meeting (ghi âm riêng từng người). ❌ với file tải lên |
| Tóm tắt / biên bản | ✅ | ✅ | ✅ (ghi vào Google Docs) | ✅ + "Visual Note" | ✅ (Ollama trên máy hoặc API) | ✅ chủ đề, ý chính, quyết định, vấn đề còn mở |
| Trích việc cần làm | ✅ "được ghi nhận và giao" tự động | ✅ | **?** | **?** | **?** (README chỉ nói tóm tắt) | ✅ người – việc – hạn – **câu gốc được kiểm tra lại bằng code** |
| Bảng công việc riêng | ❌ (**?** không thấy nêu) | ❌ đẩy sang Asana / Trello / Jira | ❌ | **?** không thấy nêu | ❌ | ✅ **Kanban kéo-thả, realtime** |
| Ghép tên trong họp ↔ thành viên | **?** | **?** | **?** | ◐ theo giọng nói đã lưu | ❌ | ✅ biệt danh, so khớp mờ, giao theo tên, **tự nhận tên** |
| Người duyệt trước khi thành việc | **?** | **?** | — | — | — | ✅ **bắt buộc** (màn hình duyệt) |
| Chi phí | Có gói miễn phí | Trả phí (có gói miễn phí giới hạn — theo bên thứ ba) | Theo gói Google Workspace | Tính theo "Coins" | Miễn phí (bản cộng đồng) | Miễn phí, chạy trên 1 laptop có GPU 4GB |

**Đọc bảng này thế nào:**
- Về **ghi chép và tóm tắt**, các sản phẩm thương mại mạnh hơn hẳn: có bot vào Zoom / Meet, hỗ trợ hàng chục tới hơn trăm ngôn ngữ, giao diện hoàn thiện, có ứng dụng di động. MeetFlow **không cạnh tranh ở điểm này**.
- **Meetily** là sản phẩm gần ý tưởng nhất (nhận dạng ngay trên máy, mã nguồn mở, ~32,8 nghìn sao trên GitHub) nhưng là ứng dụng **cho một người**, không có bảng công việc của nhóm, và nhận diện người nói nằm ở bản trả phí.
- Chỗ các sản phẩm nhóm A dừng lại là **sau khi có biên bản**: muốn việc có người chịu trách nhiệm và được theo dõi thì phải nối sang công cụ khác.

---

## 3. Nhóm B — quản lý công việc có thêm tính năng cuộc họp

| Tiêu chí | Trello | Jira (+ Loom + Rovo) | Notion (AI Meeting Notes) | **MeetFlow** |
|---|---|---|---|---|
| Bảng Kanban, hạn chót, người làm | ✅ | ✅ | ✅ (cơ sở dữ liệu dạng bảng) | ✅ |
| Tự ghi / nhận dạng cuộc họp | ❌ (trang giới thiệu không nêu; phải nối qua Zapier, Fireflies…) | ◐ qua **Loom** (sản phẩm riêng) | ✅ ghi âm thanh của máy, không cần bot | ✅ |
| Tiếng Việt | — | **?** | ✅ | ✅ |
| Từ cuộc họp → việc trên bảng | ❌ không có sẵn | ✅ lệnh `/create-work-items` với link Loom / Confluence: Rovo **đề xuất**, người dùng duyệt rồi mới tạo | ◐ tóm tắt có việc cần làm; giao việc tự động kèm người + hạn ở gói Business (theo bên thứ ba) | ✅ màn hình duyệt → "Đẩy lên bảng" trong một transaction |
| Biết ai nói | — | **?** | ◐ có nhãn người nói, hạn chế trong họp nhóm | ✅ với phòng Online Meeting |
| Âm thanh xử lý ở đâu | — | Máy chủ Atlassian | Máy chủ Notion | ✅ trên máy của nhóm |
| Điều kiện để dùng | Có gói miễn phí | Cần Jira Standard trở lên **và** bật Rovo **và** Loom AI | Tính năng AI tùy gói (**?** chưa đối chiếu chi tiết) | Tự cài, miễn phí |

**Điểm phải nói thật:** hướng "cuộc họp → việc cần làm → có người duyệt" **không phải MeetFlow nghĩ ra đầu tiên** — Jira (với Loom + Rovo) và Notion đã làm trong khoảng hai năm gần đây. Điều này *củng cố* tính đúng đắn của bài toán chứ không làm đề tài mất ý nghĩa: các hãng lớn cũng đang đi đúng hướng đó.

---

## 4. Nhóm C — LiveKit Meet

Ứng dụng họp mẫu do chính LiveKit viết (Next.js, giấy phép Apache-2.0), dùng **đúng thư viện** `@livekit/components-react` 2.9.25 như MeetFlow. Có gọi video, chia sẻ màn hình, nút ghi hình (qua dịch vụ ghi của LiveKit). **Không có** ghi âm riêng từng người, không nhận dạng giọng nói, không AI, không quản lý công việc.

→ Dùng để trả lời *"phần gọi video em tự viết tới đâu?"*: phần truyền hình / tiếng là của LiveKit (như LiveKit Meet); phần của đề tài là mọi thứ **xung quanh** nó — cấp quyền vào phòng theo nhóm, vòng đời phòng và chủ phòng, ghi âm theo người có mốc thời gian chung, gửi từng khúc chịu được rớt mạng, ghép bản ghi, lọc tiếng vọng, giao việc cho người nói.

---

## 5. Vị trí của MeetFlow

### Khoảng trống đề tài lấp vào
1. **Một hệ thống thay cho ba.** Để có cùng luồng bằng sản phẩm có sẵn cần ghép *công cụ ghi họp* + *công cụ quản lý việc* + *dịch vụ nối* (hoặc Jira Standard + Loom AI + Rovo). MeetFlow là một ứng dụng, chạy trên một laptop.
2. **Tiếng Việt và cách gọi nhau của người Việt.** Ghép "anh Nam", "Nam béo", "Su" với đúng tài khoản; đổi "thứ Sáu tuần sau", "cuối tháng" thành ngày; tách xưng hô; giữ dấu ("Năm" ≠ "Nam"). Không sản phẩm nào ở trên công bố xử lý riêng cho việc này.
3. **Người chưa có tài khoản vẫn được giao việc** (giao theo tên) và tự vào nhận tên của mình — giảm rào cản cho nhóm nhỏ.
4. **Biết ai nói bằng dữ kiện, không bằng suy đoán.** Phòng họp ghi âm riêng từng người đã đăng nhập, nên việc "để em làm" gán được cho đúng tài khoản. Các sản phẩm khác dùng nhận diện giọng nói.
5. **Âm thanh cuộc họp không rời máy của nhóm** (giống Meetily, khác các dịch vụ đám mây).
6. **Kiểm soát rủi ro của AI một cách kiểm chứng được:** câu gốc được code đối chiếu lại với bản ghi, hạn ước lượng được gắn cờ, con người bắt buộc duyệt.
7. **Có phần nghiên cứu đo đếm được** (WER, Precision / Recall / F1, có / không có nhãn người nói) — điều một sản phẩm thương mại không công bố.

### Chỗ MeetFlow yếu hơn (đưa vào mục "Hạn chế")
- Không có bot vào Zoom / Google Meet / Teams — phải tải file ghi âm lên hoặc họp trong phòng của MeetFlow.
- Phòng họp mới chạy trong **mạng LAN**; chưa có máy chủ công khai, chưa có ứng dụng di động.
- **Bước tóm tắt mặc định dùng Gemini API**: *văn bản* bản ghi (không phải âm thanh) vẫn được gửi ra ngoài. Phương án chạy hoàn toàn trên máy (Ollama) đã viết code nhưng **chưa chạy với mô hình thật**.
- Chỉ hỗ trợ tiếng Việt; chưa xuất PDF / Word; chưa gửi email.
- Số liệu mới đo trên **giọng máy đọc**, chưa có dữ liệu người thật (Giai đoạn 7).
- Độ hoàn thiện giao diện, độ ổn định và quy mô không thể so với sản phẩm thương mại.

### Câu trả lời khi hội đồng hỏi
- **"Đã có Otter / Fireflies rồi, em làm gì?"** — Các sản phẩm đó dừng ở biên bản; em làm phần sau biên bản: việc có người chịu trách nhiệm, có hạn, lên bảng của nhóm, được nhắc và theo dõi, trong cùng một hệ thống, cho tiếng Việt, với âm thanh xử lý ngay trên máy.
- **"Jira với Loom cũng tạo việc từ cuộc họp?"** — Đúng, và điều đó cho thấy hướng đi là đúng. Khác biệt: cần ba sản phẩm trả phí chạy trên đám mây; em làm một hệ thống tự triển khai, xử lý riêng cho cách xưng hô và ngày tháng tiếng Việt, và có số liệu đánh giá.
- **"Meetily mã nguồn mở, chạy trên máy, sao không dùng luôn?"** — Meetily là ứng dụng cá nhân: không có nhóm, không có bảng công việc, không giao việc; nhận diện người nói ở bản trả phí. Bài toán của em là công việc của *nhóm*.
- **"Vậy điểm mới của em là gì?"** — Không phải từng thành phần riêng lẻ, mà là (1) chuỗi khép kín ghi âm → việc được theo dõi, (2) các bước hậu xử lý cho tiếng Việt, (3) cơ chế giao theo tên / tự nhận tên, (4) ghi âm riêng từng người để biết chắc ai nói, và (5) đánh giá định lượng.

---

## 6. Việc cần làm trước khi đưa vào báo cáo
- [ ] Tự dùng thử ít nhất **Otter**, **Fireflies**, **Meetily** với cùng một đoạn họp tiếng Việt; chụp màn hình kết quả.
- [ ] Điền các ô **?** (đặc biệt: Otter / Fireflies có ghép việc với thành viên không; Meeting.ai có hỗ trợ tiếng Việt không).
- [ ] Kiểm tra lại giá và gói dịch vụ đúng ngày viết báo cáo; ghi ngày truy cập trong danh mục tài liệu tham khảo.
- [ ] (Tùy chọn, Giai đoạn 7) Lấy một sản phẩm làm mốc so sánh định lượng trên cùng bộ ghi âm.

## 7. Nguồn (truy cập 18/11/2026)
- Otter.ai — trang chủ: <https://otter.ai/> · tin mở rộng ngôn ngữ (có tiếng Việt): <https://techcrunch.com/2026/11/09/otter-ai-can-now-follow-conversations-across-30-languages/>
- Fireflies.ai — bảng ngôn ngữ hỗ trợ: <https://guide.fireflies.ai/articles/2973706448-learn-about-fireflies-supported-languages> · trang sản phẩm: <https://fireflies.ai/notetaker>
- Google Meet — ngôn ngữ hỗ trợ của Gemini trong Workspace: <https://support.google.com/meet/answer/14925782?hl=en>
- Meeting.ai — tài liệu: <https://meeting.ai/docs>
- Meetily — <https://github.com/Zackriya-Solutions/meetily> (README, bản 14/11/2026)
- Trello — <https://trello.com/tour>
- Jira / Loom / Rovo — <https://www.atlassian.com/blog/work-management/loom-ai-powered-meeting-notes> · <https://jirareleases.atlassian.com/announcements/your-meeting-decisions-already-updated-in-jira>
- Notion AI Meeting Notes — <https://www.notion.com/help/ai-meeting-notes> · <https://www.notion.com/product/ai-meeting-notes>
- LiveKit Meet — <https://github.com/livekit-examples/meet> (bản 17/11/2026)
