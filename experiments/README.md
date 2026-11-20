# THỰC NGHIỆM GIAI ĐOẠN 7 — HƯỚNG DẪN CHẠY ĐẦY ĐỦ (CHƯƠNG 4 BÁO CÁO)

Thư mục này chứa mã nguồn đánh giá định lượng cho **4 thí nghiệm** trong Chương 4:

| Thí nghiệm | Script | Đo cái gì | Đầu ra |
|---|---|---|---|
| **TN1 — STT tiếng Việt** | `exp1_stt.py` | `faster-whisper` (`small` / `medium` / `large-v3-turbo`) vs `PhoWhisper`, kèm ablation có / không `initial_prompt` | `results/exp1_stt.{json,csv,md}` + bản ghi STT trong `results/stt_transcripts/` |
| **TN2 — Trích xuất đầu việc (LLM)** | `exp2_llm.py` | `gemini-3.5-flash` vs `gemini-3.5-flash-lite` vs `Qwen2.5 3B (Ollama)`, kèm 2 nhánh ablation danh sách thành viên | `results/exp2_llm.{json,csv,md}` |
| **TN3 — End-to-End** | `exp2_llm.py --stt-dirs …` | Cùng LLM trên **bản ghi chuẩn** vs **bản ghi STT**, trên CÙNG tập cuộc họp → `ΔF1`, `ΔStrict F1`, `ΔĐúng người`, `ΔĐúng hạn` (kèm CI 95%) | `results/exp3_e2e.{json,csv,md}` |
| **TN4 — Online Meeting (GĐ6)** | `exp4_online.py` | **4A:** có vs không nhãn người nói. **4B:** lọc tiếng vọng — bản GĐ6 v1 vs bộ lọc hiện tại trên dữ liệu thật đã gán nhãn mù (+ phân tích độ nhạy mô phỏng) | `results/exp4_speakers.*` & `results/exp4_echo.*` |
| **Biểu đồ 300 DPI** | `plot_results.py` | Toàn bộ biểu đồ cho Chương 4 & slide bảo vệ | `results/charts/*.png` |

> Mọi lệnh dưới đây viết trên **1 dòng** để dán thẳng vào PowerShell (PowerShell KHÔNG hiểu ký tự nối dòng `^` của cmd; nếu muốn xuống dòng hãy dùng dấu backtick `` ` `` ở cuối dòng).

---

## 1. Chuẩn bị môi trường (làm 1 lần)

```powershell
# 1. Thư viện thực nghiệm (jiwer, matplotlib, edge-tts, httpx) vào .venv của backend
backend\.venv\Scripts\pip install -r experiments\requirements.txt

# 2. (TN2 — chạy offline) Cài Ollama tại https://ollama.com rồi kéo Qwen2.5 3B
ollama pull qwen2.5:3b

# 3. (TN1 — PhoWhisper) Chọn MỘT trong 2 cách:
#    Cách A (KHUYÊN DÙNG — cùng pipeline VAD + lọc ảo giác với Whisper): dùng bản CTranslate2 của PhoWhisper,
#      truyền qua --models fw:<repo_hoặc_thư_mục_ct2>
#    Cách B (transformers): PHẢI cài torch BẢN CUDA trước (pip install torch thường = bản CPU-only trên Windows)
backend\.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu124
backend\.venv\Scripts\pip install transformers
```

Với Cách B, nếu torch không thấy GPU thì mô hình `hf:` đó **báo lỗi và bị bỏ qua** (không âm thầm chạy CPU làm sai số liệu tốc độ); muốn cố ý chạy CPU thì thêm `--device cpu`.

---

## 2. Bộ dữ liệu (`experiments/data/`)

Mỗi cuộc họp là **1 thư mục con** (nên có **10–20 cuộc họp người thật**, 3–15 phút/cuộc):

```
experiments/data/
├── sample_meeting_01/          # Mẫu TTS 85 giây — "synthetic": true → KHÔNG tính vào số liệu Chương 4
├── meeting_12_online/
│   ├── meeting.webm            # Ghi âm (.wav, .webm, .mp3, .m4a, .ogg...)
│   ├── reference.txt           # Bản ghi chuẩn (gõ từ ghi âm, GIỮ chữ hoa tên riêng)
│   ├── reference_speakers.txt  # Bản ghi chuẩn có tên người nói "Nguyễn Văn Nam: ..." (Online Meeting, TN4A)
│   ├── expected_tasks.json     # Đáp án: ngày họp, thành viên + biệt danh, danh sách đầu việc
│   ├── echo_eval.json          # (TN4B) Các câu TRƯỚC lọc vọng, gán "is_echo": true/false
│   ├── tracks/                 # Ghi âm riêng từng người (để nghe khi gán nhãn tiếng vọng)
│   ├── online_segments.json    # Bản ghi + nhãn người nói DO HỆ THỐNG sinh (TN4A --transcript-source online_segments)
│   └── system_output.json      # ĐẦU RA CỦA HỆ THỐNG — chỉ mở SAU KHI gán nhãn xong
└── ...
```

### 2.1. Quy trình gán nhãn MÙ (bắt buộc để tránh rò rỉ đáp án)

Nếu đáp án được "sửa lại" từ chính đầu ra của MeetFlow thì WER của mô hình production bị kéo về 0, LLM sinh ra bản nháp được lợi trong TN2, và nhóm việc "tự nhận" bị định nghĩa bởi chính hệ thống. Vì vậy:

1. **Xuất cuộc họp** từ MeetFlow — script chỉ chép ghi âm, track, danh sách thành viên và tạo **template rỗng**; đầu ra của hệ thống bị tách sang `system_output.json`:
   ```powershell
   backend\.venv\Scripts\python experiments\new_meeting_template.py --export-meeting 12 --out experiments/data/meeting_12_online
   ```
2. **Gán nhãn từ ghi âm, KHÔNG mở `system_output.json` / `online_segments.json`:**
   - Gõ `reference.txt` (và `reference_speakers.txt` cho Online Meeting) — giữ chữ hoa tên riêng (tỉ lệ đúng tên chỉ đếm từ viết hoa).
   - Điền `tasks` trong `expected_tasks.json`; đánh dấu `"self_claimed": true` cho việc người nói tự nhận ("để em làm", "phần này anh lo"). Việc giao cho nhiều người → tách mỗi người 1 dòng. Tiêu đề nên ≥ 3 từ (xem luật ghép ở mục 4).
   - Nghe từng track trong `tracks/`, đổi `"is_echo": null` thành `true`/`false` cho TỪNG câu của `echo_eval.json`.
3. Đặt `"annotated": true` trong `expected_tasks.json`. **Chỉ sau đó** mới được mở `system_output.json` (VD. để phân tích lỗi).
4. **Khuyến nghị:** nhờ người thứ 2 gán nhãn độc lập khoảng 20–30% số cuộc họp và báo cáo **độ đồng thuận giữa người gán nhãn** (VD. F1 giữa 2 bộ đáp án đầu việc, Cohen's κ cho `is_echo`, WER giữa 2 bản `reference.txt`) trong Chương 4.

Cuộc họp có `"annotated": false` bị bỏ qua ở TN2/TN3/TN4A; `echo_eval.json` còn câu `is_echo: null` bị bỏ qua ở TN4B.

### 2.2. Định dạng `expected_tasks.json`
```json
{
  "meeting_date": "2026-11-20",
  "source": "online",
  "synthetic": false,
  "annotated": true,
  "members": [
    {"id": 7, "full_name": "Nguyễn Văn Nam", "nicknames": ["Nam", "anh Nam"]},
    {"id": 9, "full_name": "Trần Thị Lan", "nicknames": ["Lan", "Su"]},
    {"id": 12, "full_name": "Lê Quang Minh", "nicknames": ["Minh"]}
  ],
  "guests": ["Thầy Hùng"],
  "tasks": [
    {"assignee": "Trần Thị Lan", "task": "Viết chương 2 cơ sở lý thuyết", "due_date": "2026-11-24", "self_claimed": false},
    {"assignee": "Nguyễn Văn Nam", "task": "Chuẩn bị bộ dữ liệu thực nghiệm", "due_date": "2026-11-27", "self_claimed": true}
  ]
}
```
- `members`: **danh sách nhóm thật** (kể cả người không được giao việc). Không khai báo → script suy ra từ đáp án và **cảnh báo rò rỉ**. Với cuộc họp xuất từ MeetFlow, giữ nguyên `id` (khớp `speaker_id` trong `online_segments.json`), đừng đánh số lại.
- `guests`: người nói không có tài khoản (được phép xuất hiện trong `reference_speakers.txt`).
- `synthetic: true`: dữ liệu giả lập (TTS…) → mặc định bị loại khỏi mọi bảng số liệu; thêm `--include-synthetic` để chạy thử.

### 2.3. Kiểm tra bộ dữ liệu
```powershell
backend\.venv\Scripts\python experiments\new_meeting_template.py --validate
```
In **LỖI** (exit code 1, VD. người nói trong `reference_speakers.txt` không khớp `members`/`guests`, JSON sai, `speaker_id` lạ) và **cảnh báo** (thiếu audio, chưa gán nhãn, đáp án không khớp chính xác tên/biệt danh…). File có BOM (Notepad, PowerShell 5.1) vẫn đọc được.

---

## 3. Lệnh chạy 4 thí nghiệm & vẽ biểu đồ

### Bước 1 — TN1: So sánh mô hình STT & tác động `initial_prompt`
```powershell
backend\.venv\Scripts\python experiments\exp1_stt.py --data experiments/data --models small medium large-v3-turbo --ablate-prompt
backend\.venv\Scripts\python experiments\exp1_stt.py --data experiments/data --models large-v3-turbo hf:vinai/PhoWhisper-small hf:vinai/PhoWhisper-medium
```
- Mỗi mô hình chạy trong try/except riêng, báo cáo được ghi lại **sau mỗi mô hình** (1 mô hình lỗi/hết VRAM không làm mất kết quả các mô hình khác; mô hình lỗi được liệt kê trong báo cáo).
- VRAM báo **mức tăng so với nền** (nvidia-smi đo toàn GPU — nên tắt Ollama, trình duyệt nặng khi đo).
- **Lưu ý khi viết Chương 4:** MeetFlow chạy faster-whisper với `condition_on_previous_text=False`, nên `initial_prompt` chỉ tác động **cửa sổ 30 giây đầu** của file → tác động lên WER toàn cuộc họp bị pha loãng một cách cấu trúc. Backend `hf:` đưa gợi ý vào mọi đoạn 30 giây. Cột "Chép lại gợi ý" = số cuộc họp Whisper chép nguyên gợi ý → MeetFlow tự chạy lại KHÔNG gợi ý (dòng "có gợi ý" của cuộc đó thực chất là kết quả không gợi ý).
- Backend `hf:` không có VAD + lọc ảo giác như MeetFlow → so sánh PhoWhisper công bằng nhất là qua bản CTranslate2 (`fw:`).

### Bước 2 — TN2 & TN3: So sánh LLM & lan truyền lỗi End-to-End
```powershell
backend\.venv\Scripts\python experiments\exp2_llm.py --data experiments/data --models gemini:gemini-3.5-flash gemini:gemini-3.5-flash-lite ollama:qwen2.5:3b --ablate-members --stt-dirs experiments/results/stt_transcripts/faster-whisper__large-v3-turbo__prompt --sleep 2 --skip-existing
```
- **Temperature = 0** cho mọi provider, mỗi cấu hình chạy **1 lần**; độ bất định được thể hiện bằng **khoảng tin cậy bootstrap 95%** (2000 lần lấy mẫu lại theo cuộc họp, hạt giống cố định `20261119`).
- `--ablate-members` chạy thêm 2 nhánh: **`(bỏ DS thành viên khỏi prompt)`** — ablation CHỈ PROMPT, hậu xử lý vẫn ghép tên/biệt danh; **`(không có thành viên)`** — `members=[]`, không prompt, không ghép tên (người làm chấm theo chữ AI viết: họ tên hoặc tên gọi thật; biệt danh không tính).
- TN3: bản chuẩn được tổng hợp lại trên **đúng tập cuộc họp có bản STT** rồi mới tính Δ.
- `--skip-existing`: lưu **phản hồi thô** của LLM trong `results/cache/` (khóa = toàn bộ tham số + nội dung bản ghi + `--run-id`; khi dùng lại, từng prompt được đối chiếu). Kết quả **luôn được chấm lại** với đáp án hiện tại → sửa đáp án hay danh sách thành viên không cần gọi lại API. Gemini hết hạn mức giữa chừng: chạy lại đúng lệnh để tiếp tục. Đổi `--run-id r2` để chạy một lần độc lập.
- Cuộc họp mà LLM trả kết quả hỏng (JSON sai cấu trúc 2 lần) được ghi là **thất bại** (mọi đầu việc đáp án là FN) chứ không bị loại; lỗi mạng / hạn mức thì dừng chương trình (chạy lại với `--skip-existing`).

### Bước 3 — TN4: Nhãn người nói & Lọc tiếng vọng
```powershell
backend\.venv\Scripts\python experiments\exp4_online.py --data experiments/data --models gemini:gemini-3.5-flash gemini:gemini-3.5-flash-lite --transcript-source reference_speakers --synthetic-echo --sleep 2 --skip-existing
backend\.venv\Scripts\python experiments\exp4_online.py --data experiments/data --echo-only --synthetic-echo
```
**TN4A — cách đọc kết quả (ghi rõ trong Chương 4):**
- Hai nhánh dùng CÙNG bản ghi, CÙNG LLM; nhánh "không nhãn" bỏ mọi nhãn người nói khỏi prompt và hậu xử lý.
- `--transcript-source reference_speakers` (mặc định): nhãn người nói do người gán → kết quả là **cận trên** lợi ích của nhãn người nói. `--transcript-source online_segments`: nhãn thật do Online Meeting sinh (có lỗi STT, lọc vọng). Nguồn được ghi vào từng dòng kết quả.
- Ở nhánh "không nhãn", prompt **cấm đoán tên** người tự nhận việc → hệ thống cố ý bỏ trống, nên độ đúng việc tự nhận ≈ 0 **theo thiết kế**. Đây là so sánh hành vi hệ thống GĐ4 vs GĐ6, không phải "LLM thông minh hơn". Lỗi người làm được tách thành **bỏ trống** và **sai người**; "Việc tự nhận — recall" = số việc tự nhận giao đúng người / tổng việc tự nhận trong đáp án.

**TN4B:**
- **Kết quả chính** = dữ liệu thật `echo_eval.json` (nhãn gán mù), so **bản GĐ6 v1 (RMS thô, đóng băng trong `exp4_online.py`)** với **bộ lọc hiện tại** (`speaker_merge.drop_echoes`, gọi như hộp đen) tại **ngưỡng production**. Quét ngưỡng `--thresholds 70 75 80 85 90` chỉ là **phân tích độ nhạy** — không chọn ngưỡng tốt nhất trên chính tập đánh giá.
- `--synthetic-echo` = **phân tích độ nhạy / minh họa** trên dữ liệu mô phỏng: mức tiếng vọng 10–80% (`--echo-levels`), độ lệch độ nhạy mic **1, 2, 4, 6, 10×** (`--gains`), nhiễu RMS, nhiễu chữ, người nói có cả câu không bị vọng, `--reps 5` cuộc mỗi ô. Không dùng làm số liệu chính vì kết quả phụ thuộc giả định mô phỏng.

### Bước 4 — Biểu đồ 300 DPI
```powershell
backend\.venv\Scripts\python experiments\plot_results.py
```

---

## 4. Định nghĩa chỉ số (để trích vào Chương 4)

**Ghép đầu việc AI ↔ đáp án** (luật cố định trước khi chạy, `eval_extraction.py`):
1. `token_set_ratio` (so không dấu) ≥ **60**;
2. tập **con số** trong 2 tiêu đề phải bằng nhau ("chương 2" ≠ "chương 3"); nhận cả số viết bằng chữ ("chương hai", "mười đoạn"); bỏ qua số thuộc ngày giờ ("trước 25/11", "thứ 6", "9h");
3. tiêu đề ngắn (bên ngắn hơn **≤ 2 từ**) phải gần nguyên văn: `fuzz.ratio` ≥ **85** (tránh "Làm"/"Gửi email" khớp mọi việc);
4. ghép **1–1 tối ưu** (thuật toán Hungary): tối đa số cặp → tổng điểm tiêu đề → số cặp đúng người → số cặp đúng hạn.

Bảng **độ nhạy theo ngưỡng 50/60/70/80** và danh sách cặp đã ghép kèm điểm (`matches` trong JSON) được xuất để kiểm tra tay.

| Chỉ số | Định nghĩa |
|---|---|
| Micro P / R / F1 | Gộp TP/FP/FN của mọi cuộc họp; F1 = 2TP / (2TP + FP + FN) |
| Macro F1 | Trung bình F1 theo cuộc họp, **chỉ các cuộc có ≥ 1 đầu việc** trong đáp án |
| **Strict P / R / F1** | Đầu việc chỉ tính đúng khi khớp tiêu đề **+ đúng người + đúng hạn** (chỉ số end-to-end, dùng để so giữa các cấu hình) |
| Đúng người / Đúng hạn | Tỉ lệ trên các cặp đã khớp (mỗi cấu hình 1 tập khác nhau); lỗi người tách "bỏ trống" / "sai người" |
| Đúng hạn (việc có hạn) | Chỉ tính các việc đáp án CÓ hạn |
| Bịa hạn | Đáp án không có hạn nhưng AI gán hạn |
| CI 95% | Bootstrap theo cuộc họp (2000 lần, hạt giống cố định); Δ dùng bootstrap ghép cặp |
| "—" | Không định nghĩa (mẫu số 0) — không bao giờ ghi thành 0% |

**WER chuẩn hóa:** Unicode NFC, chữ thường, bỏ dấu câu; đổi số / ngày "25/11" / giờ "9h30" / "50%" / "2.000" / "3,5" sang chữ và quy các cách đọc tương đương (tư/bốn, mốt/một, lẻ/linh, nghìn/ngàn) ở **cả hai phía**. **Tỉ lệ đúng tên** chỉ đếm từ là tên thành viên **viết hoa** trong bản chuẩn ("miền nam", "an toàn" không tính).

Mọi bảng Markdown (`results/exp*.md`), CSV (`results/exp*.csv`, UTF-8 BOM cho Excel) và PNG (`results/charts/`) có thể đưa thẳng vào báo cáo.
