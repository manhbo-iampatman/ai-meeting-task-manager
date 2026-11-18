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

from typing import Any

from rapidfuzz import fuzz

from app.ai.postprocess.text_utils import norm_no_accent

ECHO_SIMILARITY = 80  # hai câu giống nhau từ 80% (so không dấu) thì nghi là một câu bị thu 2 lần
ECHO_MAX_SHIFT = 2.0  # tiếng vọng tới chậm hơn tiếng thật nhiều nhất cỡ 2 giây
ECHO_MIN_CHARS = 12  # câu quá ngắn ("Dạ vâng ạ") hai người nói cùng lúc là chuyện thường → không lọc

Segment = dict[str, Any]


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


def _is_echo_of(a: Segment, b: Segment) -> bool:
    """`a` có phải là bản VỌNG của `b` không (b là tiếng thật)?

    Tiếng thật to hơn tiếng vọng (tiếng vọng đi qua loa → không khí → mic, lại bị bộ khử
    vọng của trình duyệt dìm bớt). Không có số đo âm lượng thì coi bản ngắn hơn là bản vọng;
    vẫn hòa thì bản đến sau là bản vọng.
    """
    ra, rb = a.get("rms"), b.get("rms")
    if ra is not None and rb is not None and ra != rb:
        return ra < rb
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
    dropped: set[int] = set()
    for i, a in enumerate(segs):
        for j in range(i + 1, len(segs)):
            b = segs[j]
            if b["start"] > a["end"] + ECHO_MAX_SHIFT:
                break  # đã sắp theo thời gian → các câu sau còn xa hơn
            if i in dropped:
                break
            if j in dropped or a.get("speaker_id") == b.get("speaker_id"):
                continue
            if only_track is not None and only_track not in (a.get("track_id"), b.get("track_id")):
                continue
            if _same_moment(a, b) and _similar(texts[i], texts[j]):
                dropped.add(i if _is_echo_of(a, b) else j)
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
