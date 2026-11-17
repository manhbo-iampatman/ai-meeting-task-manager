"""Test tách câu theo mốc thời gian từng từ (không cần GPU)."""

from types import SimpleNamespace as NS

from app.ai.stt.faster_whisper_provider import split_sentences


def W(word, start, end):
    return NS(word=word, start=start, end=end)


def test_split_into_sentences_with_own_timestamps():
    seg = NS(start=0.0, end=9.0, text="...", words=[
        W(" Chào", 0.0, 0.4), W(" mọi", 0.4, 0.7), W(" người.", 0.7, 1.2),
        W(" Nam", 2.0, 2.3), W(" làm", 2.3, 2.5), W(" phần", 2.5, 2.8), W(" dữ", 2.8, 3.0), W(" liệu.", 3.0, 3.5),
        W(" Dạ.", 4.0, 4.3),
    ])
    out = split_sentences(seg)
    assert [s.text for s in out] == ["Chào mọi người.", "Nam làm phần dữ liệu. Dạ."]
    assert (out[0].start, out[0].end) == (0.0, 1.2)
    assert (out[1].start, out[1].end) == (2.0, 4.3)  # "Dạ." quá ngắn → nối vào câu trước


def test_no_words_keeps_segment():
    seg = NS(start=1.0, end=2.0, text=" Xin chào ", words=None)
    out = split_sentences(seg)
    assert len(out) == 1 and out[0].text == "Xin chào" and out[0].start == 1.0


def test_hallucination_filter():
    from app.ai.stt.faster_whisper_provider import is_hallucination

    def S(text, no_speech=0.1, logprob=-0.2):
        return NS(text=text, no_speech_prob=no_speech, avg_logprob=logprob)

    # Câu ảo giác thật đã gặp khi chạy thử trên RTX 3050
    assert is_hallucination(S("Hãy subscribe cho kênh La La School Để không bỏ lỡ những video hấp dẫn"))
    assert is_hallucination(S("Cảm ơn các bạn đã theo dõi"))
    assert is_hallucination(S("HÃY ĐĂNG KÝ KÊNH"))
    # Độ tin cậy thấp + nhiều khả năng không có tiếng nói
    assert is_hallucination(S("Ừm", no_speech=0.9, logprob=-1.2))
    # Câu bình thường giữ lại
    assert not is_hallucination(S("Lan viết chương hai, nộp trước thứ Sáu."))
    assert not is_hallucination(S("Cảm ơn mọi người."))


def test_prompt_echo_detection():
    from app.ai.stt.faster_whisper_provider import is_prompt_echo

    prompt = "Cuộc họp nhóm. Thành viên: Nguyễn Văn Nam (Nam, anh Nam), Trần Thị Lan (Lan, chị Lan)."
    # Lỗi thật đã gặp: file 7 giây nói không rõ → Whisper chép tên trong gợi ý ra
    assert is_prompt_echo("Nguyễn Văn Nam", prompt)
    assert is_prompt_echo("Trần Thị Lan.", prompt)
    # Câu thật có nhắc tên vẫn giữ
    assert not is_prompt_echo("Nam làm phần cơ sở dữ liệu.", prompt)
    assert not is_prompt_echo("Nguyễn Văn Nam", None)
