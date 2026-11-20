"""Ghép lời của từng người thành MỘT bản ghi có tên người nói (Online Meeting, Giai đoạn 6).

Mỗi người trong phòng họp có một file ghi âm riêng (một "track"). Whisper nhận dạng từng
file, cho ra các câu có mốc thời gian tính từ lúc file ĐÓ bắt đầu. File này làm 3 việc,
đều bằng code thường (không dùng AI) nên ổn định và test được:

  1. Dời mốc thời gian: người vào muộn 40 giây thì mọi câu của họ +40s → mọi người chung
     một trục thời gian tính từ lúc chủ phòng bấm "Bắt đầu ghi".
  2. Trộn các câu của mọi người theo thứ tự thời gian → "Nam: … / Lan: … / Nam: …".
  3. LỌC TIẾNG VỌNG: ai đó nghe bằng loa ngoài thì mic của họ thu lại tiếng người khác →
     cùng một câu xuất hiện ở track của 2 người. Giữ bản của người nói thật, bỏ bản vọng.

Vì sao không dùng AI tách người nói (diarization, vd. pyannote)? Diarization phải ĐOÁN ai
nói từ một file trộn chung, hay nhầm khi nói chen và không biết tên thật. Ở đây mỗi người
đăng nhập bằng tài khoản của mình và ghi bằng mic của mình, nên "ai nói" là dữ kiện có sẵn.
"""

from statistics import median
from typing import Any

from rapidfuzz import fuzz

from app.ai.postprocess.text_utils import norm_no_accent

ECHO_SIMILARITY = 80  # hai câu giống nhau từ 80% (so không dấu) thì nghi là một câu bị thu 2 lần
ECHO_MAX_SHIFT = 2.0  # tiếng vọng tới chậm hơn tiếng thật nhiều nhất cỡ 2 giây
ECHO_MIN_CHARS = 12  # câu quá ngắn ("Dạ vâng ạ") hai người nói cùng lúc là chuyện thường → không lọc
ECHO_REL_MARGIN = 1.35  # RMS tương đối (so với giọng bình thường của chính mic đó) chênh ≥ 1,35 lần → bên nhỏ là vọng
ECHO_SINGLE_REL_CEIL = 0.40  # chỉ 1 track có mức giọng chuẩn: câu ≤ 40% giọng bình thường của nó là vọng
ECHO_RAW_STRONG = 2.0  # không có mức giọng chuẩn: RMS thô chênh từ 2 lần trở lên mới đủ tin hơn mốc thời gian
ECHO_RAW_MARGIN = 1.25  # dự phòng cuối theo RMS thô khi mốc thời gian gần như trùng nhau
ECHO_TIME_EPS = 0.05  # âm lượng tương đương thì tiếng vọng (qua mạng + loa) luôn đến trễ hơn tiếng gốc

Segment = dict[str, Any]
TrackKey = tuple[str, int | None]


def place_segments(
    segments: list[Segment], offset: float, speaker_id: int | None, speaker: str, track_id: int
) -> list[Segment]:
    """Gắn tên người nói + dời mốc thời gian của một track lên trục thời gian chung."""
    out = []
    for s in segments:
        start = float(s.get("start") or 0.0) + offset
        end = float(s.get("end") or 0.0) + offset
        out.append(
            {
                "start": round(max(0.0, start), 2),
                "end": round(max(0.0, end), 2),
                "text": str(s.get("text", "")).strip(),
                "speaker_id": speaker_id,
                "speaker": speaker,
                "track_id": track_id,
                "rms": s.get("rms"),
            }
        )
    return [s for s in out if s["text"]]


def _similar(a: str, b: str) -> bool:
    if min(len(a), len(b)) < ECHO_MIN_CHARS:
        return False
    # partial_ratio: bản vọng thường bị cụt đầu / cụt đuôi so với câu thật
    return max(fuzz.ratio(a, b), fuzz.partial_ratio(a, b)) >= ECHO_SIMILARITY


def _same_moment(a: Segment, b: Segment) -> bool:
    """Hai câu có xảy ra cùng lúc không (chồng nhau, hoặc lệch nhau không quá 2 giây)."""
    if abs(a["start"] - b["start"]) <= ECHO_MAX_SHIFT:
        return True
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    return overlap >= 0.5 * min(a["end"] - a["start"], b["end"] - b["start"]) > 0


def _track_key(s: Segment) -> TrackKey:
    if s.get("track_id") is not None:
        return ("t", int(s["track_id"]))
    return ("s", s.get("speaker_id"))


def _track_baselines(segs: list[Segment], paired: set[int]) -> dict[TrackKey, float]:
    """Mức âm lượng nói bình thường (trung vị RMS) của từng track, tính CHỈ trên các câu
    không nghi là vọng. Nếu một người chỉ nghe loa ngoài mà không nói câu nào thì track đó
    không có baseline → tránh tự chuẩn hóa tiếng vọng thành 100%."""
    by_track: dict[TrackKey, list[float]] = {}
    for k, s in enumerate(segs):
        if k in paired:
            continue
        rms = s.get("rms")
        if rms is not None and rms > 0:
            by_track.setdefault(_track_key(s), []).append(float(rms))
    return {key: float(median(vals)) for key, vals in by_track.items()}


def _is_echo_of(a: Segment, b: Segment, baselines: dict[TrackKey, float] | None = None) -> bool:
    """`a` có phải là bản VỌNG của `b` không (b là tiếng thật)?

    Ưu tiên so **RMS tương đối** (chia cho mức giọng bình thường của chính từng mic) để tránh
    bị lừa khi mic người nghe loa ngoài nhạy/to hơn mic người nói thật:

    1. Cả hai track có mức giọng chuẩn → so RMS tương đối.
    2. Chỉ MỘT track có mức giọng chuẩn (thường gặp: người nghe loa ngoài không nói câu nào
       suốt buổi) → mức tương đối của track đó QUYẾT ĐỊNH: nói ở mức bình thường của chính nó
       (> 40%) thì nó là tiếng thật, bên kia là vọng. KHÔNG rơi về RMS thô, vì đúng trường hợp
       này mic người nghe nhạy hơn sẽ làm RMS thô của tiếng vọng to hơn tiếng thật.
    3. Không có mức giọng chuẩn nào → RMS thô nếu chênh RẤT rõ (≥ 2 lần), không thì mốc thời
       gian (tiếng vọng qua WebRTC + loa luôn đến trễ hơn), rồi RMS thô chênh vừa, cuối cùng là
       độ dài câu.
    """
    ra, rb = a.get("rms"), b.get("rms")
    if ra is not None and rb is not None:
        base = baselines or {}
        ba, bb = base.get(_track_key(a)), base.get(_track_key(b))

        # 1. RMS tương đối theo từng track
        if ba and bb and ra > 0 and rb > 0:
            rel_a, rel_b = ra / ba, rb / bb
            if rel_a * ECHO_REL_MARGIN <= rel_b:
                return True
            if rel_b * ECHO_REL_MARGIN <= rel_a:
                return False
        elif ba and not bb and ra > 0:
            # 2. Chỉ track của `a` có mức giọng chuẩn
            if ra / ba > ECHO_SINGLE_REL_CEIL:
                return False  # a nói ở mức bình thường của chính mic a → a là tiếng thật
            if a["start"] >= b["start"] - 0.2:
                return True  # a nhỏ bất thường và không đến sớm hơn → a là tiếng vọng
        elif bb and not ba and rb > 0:
            # 2. Chỉ track của `b` có mức giọng chuẩn
            if rb / bb > ECHO_SINGLE_REL_CEIL:
                return True  # b nói ở mức bình thường → b là tiếng thật, a là vọng
            if b["start"] >= a["start"] - 0.2:
                return False  # b nhỏ bất thường và không đến sớm hơn → b là tiếng vọng

        # 3. Không có mức giọng chuẩn để so: RMS thô chỉ đáng tin khi chênh RẤT rõ (mic hai người
        #    có thể lệch độ nhạy vài lần) → chênh chưa tới ECHO_RAW_STRONG thì tin mốc thời gian
        #    trước (tiếng vọng qua mạng + loa luôn đến trễ hơn), rồi mới tới RMS thô chênh vừa.
        if ra == 0 and rb > 0:
            return True
        if rb == 0 and ra > 0:
            return False
        if ra > 0 and rb > 0:
            if ra * ECHO_RAW_STRONG <= rb:
                return True
            if rb * ECHO_RAW_STRONG <= ra:
                return False
        if abs(a["start"] - b["start"]) >= ECHO_TIME_EPS:
            return a["start"] > b["start"]
        if ra > 0 and rb > 0:
            if ra * ECHO_RAW_MARGIN <= rb:
                return True
            if rb * ECHO_RAW_MARGIN <= ra:
                return False

    # Không có số đo âm lượng (hoặc vẫn hòa): bản ngắn hơn / đến sau là bản vọng
    la, lb = len(a["text"]), len(b["text"])
    if la != lb:
        return la < lb
    return a["start"] > b["start"]


def drop_echoes(segments: list[Segment], only_track: int | None = None) -> tuple[list[Segment], list[Segment]]:
    """Bỏ các câu là tiếng vọng. Trả về (giữ lại, bị bỏ).

    `only_track`: chỉ xét các cặp có dính tới track này (dùng khi bổ sung ghi âm đến muộn —
    các câu cũ đã được lọc với nhau rồi).
    """
    segs = sorted(segments, key=lambda s: (s["start"], s["end"]))
    texts = [norm_no_accent(s["text"]) for s in segs]

    # Lượt 1: tìm mọi cặp nghi là tiếng vọng để tính baseline RMS trên phần lời nói riêng
    candidates: list[tuple[int, int]] = []
    paired: set[int] = set()
    for i, a in enumerate(segs):
        for j in range(i + 1, len(segs)):
            b = segs[j]
            if b["start"] > a["end"] + ECHO_MAX_SHIFT:
                break  # đã sắp theo thời gian → các câu sau còn xa hơn
            if a.get("speaker_id") == b.get("speaker_id"):
                continue
            if _same_moment(a, b) and _similar(texts[i], texts[j]):
                candidates.append((i, j))
                paired.add(i)
                paired.add(j)

    baselines = _track_baselines(segs, paired)
    dropped: set[int] = set()
    for i, j in candidates:
        if i in dropped or j in dropped:
            continue
        a, b = segs[i], segs[j]
        if only_track is not None and only_track not in (a.get("track_id"), b.get("track_id")):
            continue
        dropped.add(i if _is_echo_of(a, b, baselines) else j)

    kept = [s for k, s in enumerate(segs) if k not in dropped]
    return kept, [segs[k] for k in sorted(dropped)]


def merge_tracks(tracks: list[list[Segment]]) -> tuple[list[Segment], list[Segment]]:
    """Ghép các track (đã `place_segments`) thành bản ghi chung. Trả về (bản ghi, các câu vọng bị bỏ)."""
    return drop_echoes([s for t in tracks for s in t])


def replace_track(existing: list[Segment], track_id: int, new: list[Segment]) -> tuple[list[Segment], list[Segment]]:
    """Bổ sung ghi âm đến muộn: thay các câu CỦA TRACK NÀY trong bản ghi bằng kết quả nhận dạng
    mới; câu của người khác (kể cả chỗ đã sửa tay) giữ nguyên."""
    others = [s for s in existing if s.get("track_id") != track_id]
    return drop_echoes(others + new, only_track=track_id)


def full_text(segments: list[Segment]) -> str:
    """Bản ghi dạng chữ, mỗi dòng "Tên người nói: câu nói"."""
    return "\n".join(f"{s['speaker']}: {s['text']}" if s.get("speaker") else s["text"] for s in segments)
