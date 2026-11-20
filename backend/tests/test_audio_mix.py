"""Test thuần (không cần Postgres / Docker) cho xử lý âm thanh Online Meeting (`audio_mix.py`)
và lọc tiếng vọng nâng cao (`speaker_merge.py`).
"""

import math
from pathlib import Path

import av
import numpy as np

from app.ai import audio_mix
from app.ai.postprocess import speaker_merge


def _write_webm(path: Path, samples: np.ndarray) -> None:
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with av.open(str(path), "w", format="webm") as out:
        stream = out.add_stream("libopus", rate=audio_mix.RATE, layout="mono")
        stream.bit_rate = 32000
        resampler = av.AudioResampler(
            format=stream.format, layout="mono", rate=audio_mix.RATE, frame_size=stream.frame_size or 960
        )
        for i in range(0, len(pcm), audio_mix.RATE):
            frame = av.AudioFrame.from_ndarray(pcm[i : i + audio_mix.RATE].reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = audio_mix.RATE
            for f in resampler.resample(frame):
                out.mux(stream.encode(f))
        for f in resampler.resample(None):
            out.mux(stream.encode(f))
        out.mux(stream.encode(None))


def _sine(duration_sec: float, freq: float, amp: float) -> np.ndarray:
    t = np.linspace(0.0, duration_sec, int(audio_mix.RATE * duration_sec), endpoint=False)
    return (amp * np.sin(2.0 * math.pi * freq * t)).astype(np.float32)


def test_soft_limit_preserves_normal_levels_and_prevents_hard_clipping():
    normal = np.array([-0.75, -0.3, 0.0, 0.4, 0.75], dtype=np.float32)
    assert np.allclose(audio_mix.soft_limit(normal), normal)

    loud = np.array([-3.0, -1.2, 0.5, 1.2, 3.0, 6.0], dtype=np.float32)
    out = audio_mix.soft_limit(loud)
    assert out[2] == 0.5
    assert np.all(np.abs(out) < 0.98)
    # Đơn điệu tăng ngay cả khi 6 người nói đè nhau, không bị cắt phẳng thành ±1.0
    assert out[3] < out[4] < out[5] < 0.98
    assert -0.98 < out[0] < out[1]


def test_streaming_rms_and_mix_files(tmp_path: Path):
    t1 = tmp_path / "t1.webm"
    t2 = tmp_path / "t2.webm"
    _write_webm(t1, _sine(2.0, 440.0, 0.6))
    _write_webm(t2, _sine(2.0, 660.0, 0.6))

    # Đo RMS theo luồng cho đoạn [0.2, 1.8]: sóng sin biên độ 0.6 có RMS lý thuyết ≈ 0.6 / sqrt(2) ≈ 0.424
    rms_list = audio_mix.segments_rms(t1, [(0.2, 1.8), (5.0, 6.0)])
    assert rms_list[0] is not None and 0.35 <= rms_list[0] <= 0.48
    assert rms_list[1] is None

    # Trộn 2 track (track 2 vào muộn 1 giây → chồng nhau ở [1s, 2s], tổng biên độ 1.2 nhưng không bị rè cứng)
    dest = tmp_path / "mixed.webm"
    ok, duration = audio_mix.mix_files([(t1, 0.0), (t2, 1.0)], dest)
    assert ok is True and dest.exists()
    assert 2.8 <= duration <= 3.2

    # File trộn giải mã lại được, có âm thanh ở cả 3 khoảng: chỉ t1, chồng t1+t2, chỉ t2
    mixed_rms = audio_mix.segments_rms(dest, [(0.2, 0.8), (1.2, 1.8), (2.2, 2.8)])
    assert all(v is not None and v > 0.2 for v in mixed_rms)


def test_truncated_webm_is_recovered_safely(tmp_path: Path):
    orig = tmp_path / "orig.webm"
    _write_webm(orig, _sine(2.0, 440.0, 0.4))
    trunc = tmp_path / "trunc.webm"
    trunc.write_bytes(orig.read_bytes()[:-200])

    # Đo RMS và cứu file sang WAV đều không crash dù gói cuối bị cụt
    rms = audio_mix.segments_rms(trunc, [(0.2, 1.2)])
    assert rms[0] is not None and rms[0] > 0.2

    wav = tmp_path / "recovered.wav"
    assert audio_mix.transcode_safe_wav(trunc, wav) is True
    assert wav.exists() and wav.stat().st_size > 16000


def test_mix_files_skips_unreadable_tracks(tmp_path: Path):
    bad = tmp_path / "not_audio.webm"
    bad.write_text("0|2|Chào mọi người.", encoding="utf-8")
    dest = tmp_path / "out.webm"
    assert audio_mix.mix_files([(bad, 0.0)], dest) == (False, 0.0)
    assert not dest.exists()
    assert audio_mix.segments_rms(bad, [(0.0, 1.0)]) == [None]


def test_speaker_merge_mismatched_mic_gain_unit():
    """Đảm bảo phần test lọc tiếng vọng chạy độc lập được ngay cả khi chưa bật Postgres."""
    nam = [
        {"start": 0.0, "end": 3.0, "text": "Chào mọi người, mình bắt đầu họp nhé.", "speaker_id": 1, "speaker": "Nam", "track_id": 1, "rms": 0.02},
        {"start": 5.0, "end": 8.0, "text": "Lan viết chương hai nộp thứ Sáu tuần này nhé.", "speaker_id": 1, "speaker": "Nam", "track_id": 1, "rms": 0.018},
    ]
    lan = [
        {"start": 5.4, "end": 8.2, "text": "viết chương hai nộp thứ sáu tuần này nhé", "speaker_id": 2, "speaker": "Lan", "track_id": 2, "rms": 0.030},
        {"start": 9.0, "end": 11.0, "text": "Dạ vâng thứ Sáu em gửi anh ạ.", "speaker_id": 2, "speaker": "Lan", "track_id": 2, "rms": 0.20},
    ]
    kept, echoes = speaker_merge.merge_tracks([nam, lan])
    assert [e["speaker_id"] for e in echoes] == [2]
    assert [s["speaker_id"] for s in kept] == [1, 1, 2]


def test_transcribe_track_recovers_truncated_file(tmp_path: Path, monkeypatch):
    """STT lỗi trực tiếp trên file bị cụt đuôi → worker tự cứu sang .wav tạm rồi nhận dạng lại và dọn file tạm."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.ai.stt.base import Segment, TranscriptResult
    from app.workers import online_jobs

    orig = tmp_path / "orig.webm"
    _write_webm(orig, _sine(2.0, 440.0, 0.4))
    trunc = tmp_path / "track_1.webm"
    trunc.write_bytes(orig.read_bytes()[:-200])

    seen_paths: list[str] = []

    class FlakySTT:
        def transcribe(self, audio_path, language="vi", on_progress=None, initial_prompt=None):
            seen_paths.append(audio_path)
            if audio_path.endswith(".webm"):
                raise RuntimeError("truncated container")
            return TranscriptResult(
                text="Xin chào mọi người.",
                segments=[Segment(0.2, 1.5, "Xin chào mọi người.")],
                language="vi",
                duration_sec=1.9,
                processing_sec=0.1,
                model="fake-stt",
            )

    now = datetime.now(UTC)
    room = SimpleNamespace(recording_started_at=now)
    track = SimpleNamespace(
        id=1,
        user_id=7,
        speaker_name="Trần Thị Lan",
        started_at=now,
        size=trunc.stat().st_size,
        segments=[],
        transcribed_size=0,
        duration_sec=None,
    )
    monkeypatch.setattr(online_jobs, "track_abspath", lambda t: trunc)

    model = online_jobs.transcribe_track(FlakySTT(), track, room, prompt=None)
    assert model == "fake-stt"
    assert len(seen_paths) == 2 and seen_paths[1].endswith(".recovered.wav")
    assert not trunc.with_suffix(".recovered.wav").exists()  # đã dọn file tạm
    assert len(track.segments) == 1 and track.segments[0]["rms"] is not None and track.segments[0]["rms"] > 0.2


def test_echo_filter_silent_listener_with_sensitive_mic_keeps_real_speaker():
    """Lan nghe loa ngoài, KHÔNG nói câu nào, mic nhạy gấp 10 lần → tiếng vọng ở track Lan có RMS thô
    TO HƠN tiếng thật của Nam. Nam có câu nói riêng (khi Lan tắt mic) → chỉ track Nam có mức giọng
    chuẩn → mức tương đối của Nam quyết định: giữ Nam, bỏ bản vọng (bản cũ bỏ nhầm cả 4 câu của Nam)."""
    lines = [
        "Tuần này mọi người tập trung vào phần nhận dạng giọng nói nhé",
        "Lan viết chương hai phần cơ sở lý thuyết nộp trước thứ sáu",
        "Minh hoàn thành trình phát âm thanh và sửa lỗi giao diện",
        "Còn phần anh thì anh sẽ chuẩn bị bộ dữ liệu thử nghiệm",
    ]

    def seg(speaker_id, start, text, rms):
        name = {1: "Nam", 2: "Lan"}[speaker_id]
        return {"start": start, "end": start + 3.0, "text": text, "speaker_id": speaker_id, "speaker": name,
                "track_id": speaker_id, "rms": rms}

    nam = [seg(1, k * 10.0, t, 0.05) for k, t in enumerate(lines)]
    nam += [seg(1, 80.0, "Mọi người cho anh xin ý kiến về lịch bảo vệ nhé", 0.05)]
    lan_echo = [seg(2, k * 10.0 + 0.3, t, 0.05 * 0.15 * 10) for k, t in enumerate(lines)]  # 0,075 > 0,05
    kept, echoes = speaker_merge.merge_tracks([nam, lan_echo])
    assert [e["speaker_id"] for e in echoes] == [2, 2, 2, 2]
    assert all(s["speaker_id"] == 1 for s in kept)


def test_echo_filter_without_any_baseline_prefers_arrival_order():
    """Không track nào có mức giọng chuẩn (mọi câu của Nam đều bị vọng, Lan không nói) và mic Lan nhạy hơn:
    RMS thô chỉ chênh 1,5 lần → chưa đủ tin → tiếng vọng là bản ĐẾN SAU."""
    text = "Lan viết chương hai phần cơ sở lý thuyết nộp trước thứ sáu"
    nam = [{"start": 5.0, "end": 8.0, "text": text, "speaker_id": 1, "speaker": "Nam", "track_id": 1, "rms": 0.05}]
    lan = [{"start": 5.3, "end": 8.3, "text": text, "speaker_id": 2, "speaker": "Lan", "track_id": 2, "rms": 0.075}]
    kept, echoes = speaker_merge.merge_tracks([nam, lan])
    assert [e["speaker_id"] for e in echoes] == [2] and [s["speaker_id"] for s in kept] == [1]
    # Chênh RẤT rõ (≥ 2 lần) thì vẫn tin âm lượng hơn thứ tự đến
    lan_loud_real = [{**lan[0], "start": 5.0, "rms": 0.2}]
    nam_late_echo = [{**nam[0], "start": 5.2, "rms": 0.02}]
    kept, echoes = speaker_merge.merge_tracks([nam_late_echo, lan_loud_real])
    assert [e["speaker_id"] for e in echoes] == [1]


def test_decode_error_mid_stream_keeps_audio_read_so_far(tmp_path: Path, monkeypatch):
    """PyAV 15 không còn `av.AVError`: gói lỗi giữa file phải được bắt bằng `av.FFmpegError`
    → giữ phần đã đọc, KHÔNG văng AttributeError (bản cũ: segments_rms trả toàn None, không cứu được file)."""
    src = tmp_path / "ok.webm"
    _write_webm(src, _sine(4.0, 220.0, 0.3))
    real_open = av.open

    class BrokenPacketsContainer:
        def __init__(self, inner):
            self.inner = inner
            self.streams = inner.streams

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.inner.close()

        def demux(self, stream):
            for n, packet in enumerate(self.inner.demux(stream)):
                if n == 60:  # khoảng giây thứ 1,2 với gói Opus 20 ms
                    raise av.error.InvalidDataError(1094995529, "gói hỏng giả lập")
                yield packet

    monkeypatch.setattr(av, "open", lambda *a, **k: BrokenPacketsContainer(real_open(*a, **k)))
    blocks = list(audio_mix._iter_pcm_blocks(src))
    got = sum(len(b) for b in blocks) / audio_mix.RATE
    assert 0.5 < got < 4.0  # giữ được phần đọc trước chỗ hỏng
    rms = audio_mix.segments_rms(src, [(0.2, 0.8)])
    assert rms[0] is not None and rms[0] > 0.1
    assert audio_mix.transcode_safe_wav(src, tmp_path / "rescued.wav")

