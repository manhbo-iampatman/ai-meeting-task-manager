"""Các job chạy trong worker. Giai đoạn 3 sẽ thêm job xử lý cuộc họp đầy đủ."""

from rq import get_current_job

from app.ai.stt import get_stt_provider


def transcribe_file_job(audio_path: str, language: str | None = "vi") -> dict:
    """Job thử nghiệm: chuyển 1 file ghi âm thành văn bản, cập nhật % tiến độ."""
    job = get_current_job()

    def on_progress(p: float) -> None:
        if job:
            job.meta["progress"] = round(p * 100)
            job.save_meta()

    result = get_stt_provider().transcribe(audio_path, language=language, on_progress=on_progress)
    return {
        "model": result.model,
        "duration_sec": result.duration_sec,
        "processing_sec": result.processing_sec,
        "text": result.text,
        "segments": [s.__dict__ for s in result.segments],
    }
