# GIẢI THÍCH GIAI ĐOẠN 5 — DUYỆT ĐẦU VIỆC, ĐẨY LÊN BẢNG, GIAO THEO TÊN & TỰ NHẬN TÊN

Giai đoạn này **đóng vòng** từ cuộc họp tới bảng công việc:

```
Bản ghi ──► AI (GĐ4) ──► ĐẦU VIỆC NHÁP ──► người DUYỆT sửa / bỏ tick ──► "Đẩy lên bảng" ──► thẻ Kanban
                                                                                          │
                       tên chưa có tài khoản ("Su", "Duy") ──► thẻ mang TÊN CHỮ (F20)     │
                                                                    │                     │
                       người đó vào nhóm ──► bấm "Đây là tôi" (F21) ┘ ──► thẻ thành của họ ┘
```

| Mã | Chức năng | Trạng thái |
|---|---|---|
| F17 | Màn hình duyệt + nút "Đẩy lên bảng" (một transaction) | ✅ |
| F18 | Truy vết: thẻ ghi "tạo từ cuộc họp X" + câu gốc, bấm mở lại cuộc họp | ✅ (phần truy vết) |
| F19 | Xuất biên bản PDF / Word | Để lượt sau (theo quyết định 17/11/2026) |
| F20 | Giao việc theo **tên chữ** khi người đó chưa có tài khoản | ✅ |
| F21 | **Tự nhận tên** (thay cho "tự gộp theo tên"), trưởng nhóm hoàn tác được | ✅ |

> **Cách thử:** `alembic upgrade head` (1 bảng + 6 cột mới), khởi động lại API và Worker AI. Mở một cuộc họp đã tóm tắt → mục **"Duyệt đầu việc"** → sửa / bỏ tick → **"⬆ Đẩy N việc lên bảng"**. Tên chưa có tài khoản hiện ở mục **"Tên chưa có người nhận"** trên trang nhóm.

**Ý tưởng xuyên suốt, nên nói ngay khi bảo vệ:** AI chỉ **đề xuất**, con người **quyết định** (*human-in-the-loop*). Ở GĐ4 hệ thống không đoán khi không chắc; ở GĐ5 người dùng là người lấp chỗ trống đó — người duyệt chọn người làm, và **chính người được gọi tên** tự xác nhận "đó là tôi".

---

## 1. Dữ liệu thay đổi (migration `d10296dc8370`)

| Bảng | Cột mới | Ý nghĩa |
|---|---|---|
| `tasks` | `assignee_name` | F20: tên chữ ("Su") khi người làm chưa có tài khoản. **Một trong hai**: hoặc `assignee_id`, hoặc `assignee_name` |
| `tasks` | `meeting_id` | F18: thẻ tạo từ cuộc họp nào (`NULL` = tạo tay). Xóa cuộc họp → `SET NULL`, thẻ vẫn còn |
| `extracted_tasks` | `assignee_name` | Tên chữ dùng khi đẩy lên bảng nếu chưa chọn tài khoản |
| `extracted_tasks` | `selected` | Có tick "đưa lên bảng" không |
| `extracted_tasks` | `task_id` | Thẻ đã tạo khi đẩy (liên kết ngược để truy vết) |
| `extracted_tasks` | `duplicate_of_task_id` | Tóm tắt lại sau khi đã đẩy: việc này giống một thẻ đã có |
| `name_claims` (bảng mới) | `name`, `name_key`, `task_ids`, `draft_ids`, `added_nickname`, `undone_at`... | **Nhật ký** mỗi lần nhận tên — lưu đủ để hoàn tác đúng những gì đã đổi |

Migration cũng **chuyển dữ liệu cũ**: đầu việc nháp từ GĐ4 có tên chưa khớp tài khoản (`assignee_match = none / ambiguous`) được điền `assignee_name = raw_assignee`.

**Vòng đời cuộc họp** thêm trạng thái `done` ("Đã lên bảng"): `review ──đẩy──► done ──tóm tắt lại──► summarizing ──► review`.

---

## 2. Duyệt & đẩy lên bảng (F17) — `services/review_service.py`

**Ai được duyệt:** trưởng nhóm + người tải cuộc họp lên (thường là "thư ký" buổi họp). Thành viên khác chỉ xem. API trả `can_review` để giao diện biết hiện ô sửa hay không.

**Màn hình duyệt** (`ExtractedTasksView.tsx`): mỗi đầu việc có ô tick, tiêu đề sửa tại chỗ, ô **người làm** (chọn thành viên *hoặc* gõ tên), **hạn chót** (chọn ngày), **ưu tiên**. Mỗi thay đổi lưu ngay (`PATCH /api/extracted-tasks/{id}`). Dưới ô người làm có dòng giải thích AI đã nghe gì ("AI nghe “anh”: người nói tự nhận việc…").

**Cảnh báo không chặn** (đã chốt): hạn "ước lượng" tô vàng, "không thấy câu gốc" tô đỏ, việc chưa có người làm được đếm ở chân trang — nhưng **không bắt** phải xử lý mới đẩy được. Chọn ngày bằng tay thì cờ "ước lượng" tự tắt.

**"Đẩy lên bảng"** (`POST /api/meetings/{id}/push`, chọn bảng, thẻ vào **cột đầu tiên**):

```
với mỗi đầu việc CHƯA đẩy:
    đang tick  → tạo Task (giữ người làm / tên chữ / hạn / ưu tiên, meeting_id) → status = accepted, task_id = thẻ mới
    bỏ tick    → status = rejected ("đã bỏ" — vẫn xem được, tick lại rồi đẩy lần sau)
cuộc họp → done
COMMIT MỘT LẦN
```

**Vì sao một transaction?** Hàm service chỉ `flush` (để có `task.id`), route `commit` **một lần** ở cuối. Lỗi giữa chừng (vd. bảng không thuộc nhóm) → không thẻ nào được tạo, không có trạng thái "đẩy được một nửa". Test `test_push_to_board_of_other_workspace_is_rejected` kiểm đúng điều này.

Người được giao (có tài khoản) nhận thông báo "được giao việc" như khi giao tay (dùng lại F08).

### Tóm tắt lại sau khi đã đẩy (đã chốt: vẫn cho phép)
- Đầu việc **đã đẩy được giữ lại** (để truy vết), chỉ đầu việc chưa đẩy bị thay.
- Việc mới **trùng** một việc đã đẩy (cùng người làm + `same_task` của GĐ4) → nhãn **"đã có trên bảng"** và **bỏ tick sẵn**. Việc mới không rõ người làm mà trùng nội dung cũng coi là trùng.
- Người duyệt vẫn tick lại được nếu thật sự muốn tạo thêm.

---

## 3. Giao việc theo tên (F20)

Trước GĐ5, mỗi thẻ chỉ giao được cho **một tài khoản**. Nhưng quyết định 16/11 là *chỉ người tổ chức họp bắt buộc có tài khoản* → họp xong, Lan và Minh chưa đăng ký thì việc của họ không lên bảng được.

**Giải pháp:** thêm `tasks.assignee_name`. Ô chọn người làm (`AssigneePicker.tsx`, dùng chung cho màn hình duyệt và cửa sổ chi tiết thẻ) có thêm mục **"✎ Người chưa có tài khoản (gõ tên)…"**. Thẻ hiện tên trong khung viền đứt để phân biệt với avatar thành viên.

Quy tắc ở API: gửi `assignee_id` thì xóa `assignee_name`; gửi tên khác rỗng thì xóa `assignee_id` → không bao giờ có cả hai.

**Đại từ không thành tên:** việc "để em làm" (`assignee_match = self`) và "cả nhóm" (`group`) **không** được điền tên chữ — "em" không phải tên ai cả. Nếu không ai chọn người, thẻ lên bảng với "chưa có người làm" (đã chốt).

---

## 4. Tự nhận tên (F21) — `services/name_claim_service.py`

**Vấn đề:** trong họp người ta gọi nhau bằng biệt danh, tên thân mật, tên giả ("Su", "anh Hai"). Tài khoản tên "Trần Thị Lan" thì máy **không thể** biết "Su" là Lan. Kế hoạch cũ "khi Lan đăng ký thì tự gộp theo tên" sẽ hỏng ngay.

**Ý tưởng (do người làm khóa luận đề xuất):** hiện danh sách **"Tên chưa có người nhận"** trên trang nhóm; ai thấy tên mình thì bấm **"🙋 Đây là tôi"**.

### Danh sách tên chờ nhận
Gom từ **thẻ trên mọi bảng** (`assignee_name`, chưa có `assignee_id`) **và đầu việc nháp chưa đẩy** của nhóm (ghi rõ "chờ duyệt" hay "đã bỏ").

**Ai thấy danh sách** (sửa 18/11/2026 sau khi dùng thử): thành viên **chưa nhận tên nào**. Đã nhận một tên (chưa bị hoàn tác) thì danh sách **ẩn hẳn** — vd. Lan nhận "Lan" xong thì không còn thấy tên "Minh" và nút "Đây là tôi" nữa, tránh nhận nhầm tên người khác. Trưởng nhóm hoàn tác thì Lan thấy lại. Ẩn ở **phía server** (`has_claimed` → API trả danh sách rỗng), không chỉ ẩn trên giao diện.

**Gộp các cách viết** (`name_key`): bỏ xưng hô + không phân biệt hoa/thường, nhưng **giữ dấu**:

| Cách viết | Khóa | Ghi chú |
|---|---|---|
| "Lan", "lan", "chị Lan" | `lan` | một tên |
| "Năm" | `năm` | khác "Nam" — trong tiếng Việt là hai tên khác nhau |

**Gợi ý "Bạn có phải là Lan không?"**: dùng lại **đúng hàm ghép tên của GĐ4** (`match_name`) giữa tên đang chờ và họ tên + biệt danh của người đang xem. Khớp mức exact / bỏ dấu / gần giống → tên đó lên đầu danh sách, viền nổi bật. Chỉ **gợi ý**, không bao giờ tự nhận thay.

### Bấm "Đây là tôi" — có hiệu lực NGAY
Trong một transaction:
1. Mọi thẻ + đầu việc nháp mang tên đó → chuyển cho người nhận.
2. Tên được thêm vào **biệt danh** của họ trong nhóm (nếu chưa có biệt danh tương đương).
3. Ghi một dòng `name_claims` (danh sách id đã đổi, biệt danh đã thêm).
4. Thông báo **một lần, tổng hợp**: người nhận "Bạn đã nhận tên “Su”: 3 việc giờ là của bạn"; trưởng nhóm "Lan đã nhận tên “Su” (3 việc)" **kèm nút ↩ Hoàn tác**.
5. Sự kiện realtime `names_updated` → trang nhóm, trang cuộc họp đang mở tự tải lại.

**Vì sao lưu thành biệt danh là điểm hay nhất?** Đây là **vòng phản hồi**: biệt danh chính là dữ liệu GĐ4 dùng để ghép tên (đưa vào prompt + `match_name`). Lan nhận "Su" một lần → **cuộc họp sau AI tự hiểu "Su" là Lan**, không ai phải nhận lại. Test `test_claim_applies_to_drafts_and_teaches_ai` chứng minh đúng chuỗi này.

### Hoàn tác (chỉ trưởng nhóm)
`POST /api/name-claims/{id}/undo`: trả các thẻ / đầu việc **vẫn đang thuộc người đã nhận** về lại tên chữ (việc đã được giao lại cho người khác sau đó thì giữ nguyên), kể cả thẻ được đẩy lên bảng **sau** khi nhận từ đầu việc nháp đã ghép; gỡ biệt danh vừa thêm; thông báo của trưởng nhóm đổi thành "Đã hoàn tác"; người đã nhận được báo.

**Vì sao "nhận ngay + hoàn tác" chứ không "chờ duyệt"?** (đã chốt) Nhóm làm việc thường tin nhau; bắt trưởng nhóm duyệt từng lần nhận là thêm một bước cho trường hợp hiếm. Nhật ký `name_claims` bảo đảm nhận nhầm / nhận bậy vẫn sửa được chính xác.

---

## 5. Quyền trên thẻ (sửa 18/11/2026 sau khi dùng thử)

**Sự cố:** khi thử, tài khoản Lan kéo được thẻ của Nam sang "Hoàn thành". Nguyên nhân: từ GĐ2, bảng được thiết kế kiểu Trello — thành viên nào cũng tạo / sửa / kéo / xóa được mọi thẻ.

**Quyết định mới:** **kéo thả, sửa nội dung, xóa** một thẻ chỉ dành cho:

| Ai | Vì sao |
|---|---|
| Người làm (`assignee_id`) | Việc của mình thì tự cập nhật tiến độ |
| Người tạo thẻ (`created_by`) | Người giao việc sửa lại được nội dung đã giao. Thẻ từ cuộc họp: người đã bấm "Đẩy lên bảng" |
| Trưởng nhóm | Quản lý chung |

Thành viên khác **chỉ xem và bình luận**. Thẻ chưa có người làm hoặc giao theo tên chữ → chỉ người tạo + trưởng nhóm. Người làm giao lại việc cho người khác thì mất quyền trên thẻ đó.

**Hai lớp kiểm tra:**
- **Backend** (`can_edit_task` / `require_task_editor` trong `api/deps.py`) chặn `PATCH`, `POST …/move`, `DELETE` bằng lỗi 403 — đây là lớp bảo đảm thật.
- **Giao diện** (`lib/permissions.ts`, cùng quy tắc): thẻ không có quyền thì không kéo được (con trỏ bàn tay + chú thích), cửa sổ chi tiết khóa mọi ô, ẩn nút xóa, hiện dòng 🔒 giải thích. Lớp này chỉ để người dùng hiểu, không thay được lớp backend.

`BoardDetail` trả thêm `owner_id` để giao diện biết ai là trưởng nhóm.

---

## 6. Truy vết nguồn gốc (F18, phần truy vết)

- Thẻ tạo từ cuộc họp có biểu tượng 🎙 trên bảng.
- Cửa sổ chi tiết thẻ: **"🎙 Tạo từ cuộc họp *Họp ngày 17/11* · phút 0:21"** + câu gốc, bấm mở lại cuộc họp.
- Trang cuộc họp: mục **"✓ Đã lên bảng"** liệt kê việc đã đẩy, mỗi việc có link "Mở thẻ".

Nhờ `extracted_tasks.task_id` ↔ `tasks.meeting_id`, đi được **cả hai chiều**: từ cuộc họp tới thẻ và từ thẻ về câu nói gốc.

---

## 7. API mới

| Phương thức | Đường dẫn | Việc |
|---|---|---|
| PATCH | `/api/extracted-tasks/{id}` | Sửa đầu việc nháp (tiêu đề, người làm / tên, hạn, ưu tiên, tick) |
| POST | `/api/meetings/{id}/push` | Đẩy các việc đang tick lên bảng `board_id` |
| GET | `/api/workspaces/{id}/pending-names` | Danh sách tên chưa có người nhận (+ cờ gợi ý cho người đang xem) |
| POST | `/api/workspaces/{id}/pending-names/claim` | Nhận một tên |
| POST | `/api/name-claims/{id}/undo` | Trưởng nhóm hoàn tác |

Thêm vào: `TaskCreate/TaskUpdate.assignee_name`, `TaskOut.assignee_name / meeting_id`, `TaskDetail.source`, `MeetingDetail.can_review`.

---

## 8. Kiểm thử

**143 test tự động** (thêm 14 test trong `tests/test_review.py`):

| Test | Kiểm tra |
|---|---|
| `test_drafts_keep_unmatched_name_as_text` | "Duy" chưa có tài khoản → tên chữ; "anh" (đại từ) → KHÔNG thành tên |
| `test_only_owner_and_uploader_can_review` | Trưởng nhóm + người tải lên duyệt được; thành viên khác bị 403 |
| `test_edit_draft` | Chọn thành viên / gõ tên / để trống; người ngoài nhóm bị chặn; sửa hạn tắt cờ ước lượng |
| `test_push_creates_cards_in_one_go` | Thẻ vào cột đầu, giữ người làm / tên / hạn; việc bỏ tick → "đã bỏ"; tick lại rồi đẩy thêm; F18 nguồn gốc |
| `test_push_notifies_assignee` | Người được giao nhận thông báo |
| `test_push_to_board_of_other_workspace_is_rejected` | Lỗi → không có thẻ nào bị tạo dở dang |
| `test_resummarize_after_push_marks_duplicates` | Việc đã đẩy được giữ; việc trùng bỏ tick sẵn; đẩy lần 2 không tạo thẻ trùng |
| `test_manual_task_with_name_assignee` | F20 trên thẻ tạo tay |
| `test_pending_names_group_spellings` | "Duy" / "anh Duy" / "duy" gộp; "Năm" ≠ "Nam Anh" |
| `test_claim_and_undo` | Gợi ý đúng người; nhận → thẻ chuyển + biệt danh + thông báo; người khác không nhận lại được; chỉ trưởng nhóm hoàn tác; hoàn tác 2 lần bị chặn |
| `test_claim_applies_to_drafts_and_teaches_ai` | Nhận khi còn nháp; hoàn tác cả thẻ đẩy sau khi nhận; **cuộc họp sau AI tự ghép qua biệt danh** |
| `test_pending_list_hidden_after_claim` | Nhận tên xong → danh sách rỗng với người đó, người khác vẫn thấy; hoàn tác → thấy lại |
| `test_pending_draft_reports_its_status` | Đầu việc nháp trong danh sách ghi đúng "chờ duyệt" / "đã bỏ" |
| `test_only_assignee_creator_or_owner_can_change_a_card` | Người làm / người tạo / trưởng nhóm kéo + sửa được; người khác 403 nhưng vẫn xem + bình luận; thẻ tên chữ chỉ người tạo + trưởng nhóm; giao lại thì mất quyền |

**Kiểm thử thật trên trình duyệt (17/11/2026, cuộc họp 11):** bỏ tick 1 việc → nút đổi "Đẩy 3 việc"; đẩy lên "Bảng chính" → 3 thẻ ở cột "Cần làm", thẻ "Lan" hiện tên viền đứt + 🎙; chi tiết thẻ hiện nguồn gốc + câu gốc; trang nhóm hiện "Lan (2 việc)", "Minh (1 đầu việc chờ duyệt)". Một tài khoản test "Trần Thị Lan" vào nhóm và nhận tên (qua API) → trang nhóm của trưởng nhóm **tự cập nhật không cần tải lại**; chuông thông báo có nút Hoàn tác, bấm → tên "Lan" trở lại danh sách, biệt danh bị gỡ, thông báo đổi thành "Đã hoàn tác".

**Sau khi sửa (18/11/2026), đăng nhập tài khoản test Lan:** trang nhóm không còn mục "Tên chưa có người nhận"; trên bảng 2 thẻ của Lan kéo được, thẻ của Nam bị khóa; mở thẻ của Nam: mọi ô bị khóa, không có nút xóa, có dòng 🔒, ô bình luận vẫn dùng được. Qua API: Lan kéo / sửa thẻ của Nam → 403, bình luận → 201.

**Chưa thử trên trình duyệt (phía người làm khóa luận đã tự bấm thử):** bấm nút "Đây là tôi" bằng chính giao diện (mới kiểm qua API và test tự động, vì trình duyệt trong app không mở được tài khoản thứ hai song song); giao diện trên điện thoại.

---

## Tự kiểm tra

1. *Human-in-the-loop* là gì? GĐ5 thể hiện nó ở những chỗ nào?
2. Vì sao "Đẩy lên bảng" phải là một transaction? Nếu không thì có thể xảy ra chuyện gì?
3. Ai được duyệt đầu việc? Vì sao không cho mọi thành viên?
4. Tóm tắt lại sau khi đã đẩy thì việc trùng được xử lý thế nào? Dùng lại hàm nào của GĐ4?
5. F20 giải quyết vấn đề gì? Vì sao "em", "anh" không được lưu thành tên chữ?
6. Vì sao không tự gộp tên vào tài khoản khi người đó đăng ký mà phải để họ tự nhận?
7. "Lan", "chị Lan", "Năm", "Nam" — cái nào gộp, cái nào không, vì sao?
8. Gợi ý "Bạn có phải là Lan?" được tính bằng gì? Vì sao chỉ gợi ý mà không tự nhận?
9. Lưu tên vừa nhận thành biệt danh giúp gì cho các cuộc họp sau?
10. Hoàn tác trả lại những gì? Vì sao cần bảng `name_claims`?
11. Từ một thẻ trên bảng, làm sao biết nó sinh ra từ câu nói nào trong cuộc họp nào?
12. Ai được kéo / sửa / xóa một thẻ? Vì sao phải chặn ở backend chứ không chỉ ẩn nút trên giao diện?
13. Vì sao người đã nhận tên không thấy danh sách nữa? Ẩn ở đâu?
