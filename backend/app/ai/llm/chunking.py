"""Chia bản ghi dài thành nhiều đoạn vừa sức đọc của mô hình (bước "map" của map-reduce).

    Bản ghi dài ──chia──► đoạn 1, đoạn 2, đoạn 3
                             │        │        │        (map: mỗi đoạn gọi LLM 1 lần)
                         tóm tắt + đầu việc từng đoạn
                             └────────┼────────┘        (reduce: gộp lại)
                          1 biên bản + 1 danh sách đầu việc

- Cắt ở RANH GIỚI CÂU (không cắt giữa câu) để không làm vỡ nghĩa.
- Hai đoạn liền nhau GỐI lên nhau vài câu (overlap): một việc được giao bằng 2 câu
  nằm đúng chỗ cắt ("Phần báo cáo thì..." / "...Lan làm nhé, hạn thứ Sáu") vẫn nằm
  trọn trong ít nhất một đoạn. Đầu việc bị trích 2 lần do gối đầu sẽ được khử trùng sau.
"""


def chunk_lines(lines: list[str], max_chars: int, overlap: int = 2) -> list[list[str]]:
    if max_chars <= 0:
        return [lines]
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        cost = len(line) + 1  # +1 cho ký tự xuống dòng
        if current and size + cost > max_chars:
            chunks.append(current)
            current = current[-overlap:] if overlap > 0 else []
            size = sum(len(x) + 1 for x in current)
            if size + cost > max_chars:  # phần gối đầu + câu mới đã quá dài → bỏ gối đầu
                current, size = [], 0
        current.append(line)  # một câu dài hơn cả giới hạn vẫn được giữ nguyên, thành 1 đoạn riêng
        size += cost
    if current:
        chunks.append(current)
    return chunks
