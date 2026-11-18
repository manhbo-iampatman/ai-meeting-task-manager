"""Job của worker cho Online Meeting (Giai đoạn 6): nhận dạng ghi âm riêng của TỪNG NGƯỜI rồi
ghép thành một bản ghi có tên người nói.

    track của Nam ──► Whisper ──► các câu của Nam (dời mốc thời gian) ─┐
    track của Lan ──► Whisper ──► các câu của Lan (dời mốc thời gian) ─┼─► trộn theo thời gian
    track của Minh ─► Whisper ──► các câu của Minh ────────────────────┘    + lọc tiếng vọng
                                                                              │
                                              bản ghi "Nam: … / Lan: … / Minh: …" ──► pipeline GĐ4

GPU 4GB chỉ chạy được một việc mỗi lúc → các track được nhận dạng LẦN LƯỢT.
"""

import logging
import time

from sqlalchemy import select

from app.ai import audio_mix
from app.ai.postprocess import speaker_merge
from app.ai.stt import get_stt_provider
from app.core.database import SessionLocal
from app.models import Meeting, MeetingRoom, MeetingStatus, MeetingTrack, Transcript
from app.services.meeting_service import notify_meeting, upload_root
from app.services.room_service import track_abspath
from app.workers.jobs import build_initial_prompt

log = logging.getLogger(__name__)


def _room_of(db, meeting: Meeting) -> MeetingRoom | None:
    return db.scalar(select(MeetingRoom).where(MeetingRoom.meeting_id == meeting.id))


def track_offset(track: MeetingTrack, room: MeetingRoom) -> float:
    """Track này bắt đầu sau lúc chủ phòng bấm "Bắt đầu ghi" bao nhiêu giây (người vào muộn > 0)."""
    if room.recording_started_at is None:
        return 0.0
    return max(0.0, (track.started_at - room.recording_started_at).total_seconds())


def transcribe_track(stt, track: MeetingTrack, room: MeetingRoom, prompt: str | None, on_progress=None):
    """Nhận dạng ghi âm của MỘT người → lưu các câu (đã dời lên trục thời gian chung, kèm âm lượng)
    vào `track.segments`. Trả về (mảng âm thanh đã giải mã để trộn file nghe lại, tên mô hình)."""
    path = track_abspath(track)
    size_before = track.size  # trong lúc nhận dạng có thể vẫn còn khúc về thêm (người rớt mạng)
    if path is None or not path.exists() or size_before == 0:
        track.segments, track.transcribed_size = [], size_before
        return None, None
    result = stt.transcribe(str(path), language="vi", on_progress=on_progress, initial_prompt=prompt)
    audio = audio_mix.load_audio(path)
    raw = [
        {"start": s.start, "end": s.end, "text": s.text, "rms": audio_mix.segment_rms(audio, s.start, s.end)}
        for s in result.segments
    ]
    track.segments = speaker_merge.place_segments(
        raw, track_offset(track, room), track.user_id, track.speaker_name, track.id
    )
    track.transcribed_size = size_before
    track.duration_sec = result.duration_sec
    return audio, result.model


def write_mix(m: Meeting, mixer: audio_mix.Mixer) -> None:
    """Trộn ghi âm của mọi người thành MỘT file để nghe lại cả buổi họp ở trang cuộc họp."""
    folder = upload_root() / "meetings"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{m.id}.webm"
    if mixer.write(dest):
        m.audio_path = str(dest.relative_to(upload_root()))
        m.audio_filename = f"online-meeting-{m.id}.webm"
        m.audio_size = dest.stat().st_size
        m.audio_mime = "audio/webm"


def save_transcript(db, m: Meeting, segments: list[dict], model: str | None, duration: float, took: float) -> Transcript:
    tr = m.transcript or Transcript(meeting_id=m.id)
    tr.segments = segments
    tr.full_text = speaker_merge.full_text(segments)
    tr.language = "vi"
    tr.stt_model = model or tr.stt_model
    tr.duration_sec = round(max(duration, max((s["end"] for s in segments), default=0.0)), 2)
    tr.processing_sec = round(took, 2)
    db.add(tr)
    return tr


def _fail(db, m: Meeting, message: str) -> dict:
    m.status, m.error, m.status_note = MeetingStatus.FAILED, message, None
    db.commit()
    notify_meeting(m)
    return {"error": message}


def process_online_meeting_job(meeting_id: int) -> dict:
    """Cuộc họp Online Meeting: nhận dạng từng người, ghép bản ghi có TÊN NGƯỜI NÓI, lọc tiếng
    vọng, trộn một file nghe lại."""
    t0 = time.perf_counter()
    with SessionLocal() as db:
        m = db.get(Meeting, meeting_id)
        if m is None:  # cuộc họp đã bị xóa trong lúc chờ
            return {"skipped": True}
        room = _room_of(db, m)
        tracks = [t for t in (room.tracks if room else []) if t.size > 0]
        if room is None or not tracks:
            return _fail(db, m, "Không tìm thấy ghi âm của cuộc họp trên máy chủ")

        m.status, m.progress, m.error, m.status_note = MeetingStatus.TRANSCRIBING, 0, None, None
        db.commit()
        notify_meeting(m)

        # Báo tiến độ: tối đa ~1 lần/giây và chỉ khi tăng ≥ 1%
        last = {"pct": 0, "t": 0.0}

        def progress_for(i: int):
            def on_progress(p: float) -> None:
                pct = min(95, int((i + p) / len(tracks) * 95))
                now = time.monotonic()
                if pct > last["pct"] and now - last["t"] >= 1.0:
                    last.update(pct=pct, t=now)
                    m.progress = pct
                    db.commit()
                    notify_meeting(m)

            return on_progress

        try:
            stt = get_stt_provider()
        except Exception as e:  # noqa: BLE001 — không nạp được mô hình (hết VRAM...)
            log.exception("Không nạp được mô hình STT cho cuộc họp %s", meeting_id)
            return _fail(db, m, f"Lỗi xử lý ghi âm: {type(e).__name__}: {str(e)[:300]}")

        prompt = build_initial_prompt(db, m.workspace_id)
        mixer = audio_mix.Mixer()
        errors: list[str] = []
        model: str | None = None
        for i, t in enumerate(tracks):
            try:
                audio, used = transcribe_track(stt, t, room, prompt, progress_for(i))
                model = used or model
                mixer.add(audio, track_offset(t, room))
            except Exception as e:  # noqa: BLE001 — một file hỏng không được làm hỏng cả cuộc họp
                log.exception("Cuộc họp %s: lỗi nhận dạng ghi âm của %s", meeting_id, t.speaker_name)
                errors.append(f"{t.speaker_name}: {type(e).__name__}: {str(e)[:200]}")
                t.segments, t.transcribed_size = [], t.size
            db.commit()

        merged, echoes = speaker_merge.merge_tracks([t.segments for t in tracks])
        if echoes:
            log.info("Cuộc họp %s: bỏ %d câu là tiếng vọng: %s", meeting_id, len(echoes), [e["text"] for e in echoes])

        db.refresh(m)
        if not merged:
            if len(errors) == len(tracks):
                return _fail(db, m, "Lỗi xử lý ghi âm: " + "; ".join(errors))
            return _fail(
                db, m, "Không nhận ra lời nói trong ghi âm của buổi họp (không ai nói, hoặc mic của mọi người đều tắt)."
            )

        tr = save_transcript(db, m, merged, model, mixer.duration_sec, time.perf_counter() - t0)
        tr.edited = False
        write_mix(m, mixer)
        for t in tracks:
            t.merged = True
        m.status, m.progress = MeetingStatus.TRANSCRIBED, 100
        db.commit()
        notify_meeting(m)
        log.info(
            "Cuộc họp online %s: %d người, %d câu, bỏ %d câu vọng, xử lý %.1fs",
            meeting_id, len(tracks), len(merged), len(echoes), time.perf_counter() - t0,
        )
        return {"tracks": len(tracks), "segments": len(merged), "echoes": len(echoes), "errors": errors}


def process_late_track_job(track_id: int, force: bool = False) -> dict:
    """Ghi âm của một người về SAU khi cuộc họp đã được nhận dạng (rớt mạng, đóng tab đột ngột).

    - Nhận dạng lại track đó (nếu có phần mới).
    - Bản ghi chưa bị sửa tay và chưa tóm tắt → TỰ bổ sung lời của người đó vào bản ghi.
    - Ngược lại → để chờ (`merged = False`); người duyệt bấm "Bổ sung" (force=True) mới đưa vào,
      vì tự ghi đè lên bản ghi người ta đã sửa / đã dùng để tóm tắt là không an toàn.
    """
    t0 = time.perf_counter()
    with SessionLocal() as db:
        track = db.get(MeetingTrack, track_id)
        m = db.get(Meeting, track.meeting_id) if track and track.meeting_id else None
        if track is None or m is None:
            return {"skipped": True}
        room = track.room
        if m.status in MeetingStatus.PROCESSING:  # job chính chưa xong (hiếm) → nó sẽ tự lo track này
            return {"skipped": "meeting is processing"}

        model: str | None = None
        if track.has_new_audio or not track.segments:
            try:
                _, model = transcribe_track(get_stt_provider(), track, room, build_initial_prompt(db, m.workspace_id))
            except Exception as e:  # noqa: BLE001
                log.exception("Lỗi nhận dạng ghi âm đến muộn (track %s)", track_id)
                db.rollback()
                return {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            track.merged = False
            db.commit()

        tr = m.transcript
        untouched = tr is None or (not tr.edited and m.summary is None)
        if not (force or untouched):
            notify_meeting(m)  # trang cuộc họp hiện nút "Bổ sung ghi âm của …"
            return {"pending": True}

        merged, echoes = speaker_merge.replace_track(list(tr.segments) if tr else [], track.id, track.segments)
        if not merged:  # vẫn không có câu nào (track đến muộn cũng im lặng)
            track.merged = True
            db.commit()
            return {"empty": True}
        was_edited = bool(tr and tr.edited)
        duration = (tr.duration_sec or 0.0) if tr else 0.0
        tr = save_transcript(db, m, merged, model, duration, time.perf_counter() - t0)
        tr.edited = was_edited
        track.merged = True
        if m.status == MeetingStatus.FAILED:  # trước đó "không nhận ra lời nói" → giờ đã có
            m.status, m.error, m.progress = MeetingStatus.TRANSCRIBED, None, 100

        # Trộn lại file nghe lại cho có cả tiếng của người đến muộn
        mixer = audio_mix.Mixer()
        for t in room.tracks:
            if t.size > 0 and (p := track_abspath(t)) is not None:
                mixer.add(audio_mix.load_audio(p), track_offset(t, room))
        write_mix(m, mixer)
        db.commit()
        notify_meeting(m)
        log.info("Cuộc họp %s: bổ sung ghi âm của %s (%d câu)", m.id, track.speaker_name, len(track.segments))
        return {"merged": True, "segments": len(track.segments), "echoes": len(echoes)}
