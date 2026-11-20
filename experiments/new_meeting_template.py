"""Công cụ quản lý bộ dữ liệu thực nghiệm Giai đoạn 7 (`experiments/data/`).

  1. `--new <tên>`: tạo thư mục mẫu đúng cấu trúc (`reference.txt`, `reference_speakers.txt`,
     `expected_tasks.json`, tùy chọn `echo_eval.json`) để xem định dạng.
  2. `--export-meeting <id> --out <thư_mục>`: xuất một cuộc họp đã chạy thật trong MeetFlow theo
     QUY TRÌNH GÁN NHÃN MÙ (blind annotation) — tránh rò rỉ kết quả của hệ thống vào đáp án:
       * Ghi âm (`meeting.*`) + track riêng từng người (`tracks/`), thông tin thành viên/biệt danh.
       * Template RỖNG để người gán nhãn tự làm từ ghi âm: `reference.txt`, `reference_speakers.txt`
         (chỉ với Online Meeting), `expected_tasks.json` (đã điền ngày họp, nguồn, `members`, nhưng
         `tasks: []` và `"annotated": false`; `self_claimed` do người gán nhãn tự đánh dấu).
       * `echo_eval.json` (chỉ Online Meeting): các câu TRƯỚC khi lọc vọng với `"is_echo": null` —
         gán nhãn bằng cách NGHE track, không nhìn kết quả lọc.
       * Đầu ra CỦA HỆ THỐNG (bản ghi STT, đầu việc AI, câu từng track) tách riêng vào
         `system_output.json` — CHỈ mở SAU KHI đã gán nhãn xong.
       * `online_segments.json` (bản ghi + nhãn người nói do Online Meeting sinh, dùng cho
         TN4A `--transcript-source online_segments`) — chỉ với cuộc họp online có `speaker_id`.
  3. `--validate [thư_mục]`: kiểm tra hợp lệ bộ dữ liệu, tách LỖI (exit 1) và CẢNH BÁO, thống kê số
     cuộc họp sẵn sàng cho từng thí nghiệm (cuộc họp giả lập / chưa gán nhãn không được tính).

Ví dụ (PowerShell, 1 dòng):
  backend\\.venv\\Scripts\\python experiments\\new_meeting_template.py --validate
  backend\\.venv\\Scripts\\python experiments\\new_meeting_template.py --new meeting_02_online --with-echo
  backend\\.venv\\Scripts\\python experiments\\new_meeting_template.py --export-meeting 12 --out experiments/data/meeting_12_online
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DEFAULT_DATA_DIR,
    discover_meetings,
    load_backend_settings,
    validate_meeting,
    write_json,
)


def create_template(folder: Path, with_echo: bool = False) -> None:
    if folder.exists() and any(folder.iterdir()):
        raise SystemExit(f"Thư mục đã tồn tại và không rỗng: {folder}")
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "reference.txt").write_text(
        "Chào mọi người, mình bắt đầu buổi họp nhé.\n"
        "Lan làm slide báo cáo, gửi trước thứ Sáu tuần này nhé.\n"
        "Dạ phần demo để em chuẩn bị ạ.\n",
        encoding="utf-8",
    )
    (folder / "reference_speakers.txt").write_text(
        "Nguyễn Văn Nam: Chào mọi người, mình bắt đầu buổi họp nhé.\n"
        "Nguyễn Văn Nam: Lan làm slide báo cáo, gửi trước thứ Sáu tuần này nhé.\n"
        "Trần Thị Lan: Dạ phần demo để em chuẩn bị ạ.\n",
        encoding="utf-8",
    )
    write_json(
        folder / "expected_tasks.json",
        {
            "meeting_date": date.today().isoformat(),
            "source": "online",
            "synthetic": False,
            "annotated": False,
            "members": [
                {"id": 1, "full_name": "Nguyễn Văn Nam", "nicknames": ["Nam", "anh Nam"]},
                {"id": 2, "full_name": "Trần Thị Lan", "nicknames": ["Lan", "Su"]},
            ],
            "guests": [],
            "tasks": [
                {"assignee": "Trần Thị Lan", "task": "Làm slide báo cáo", "due_date": None, "self_claimed": False},
                {"assignee": "Trần Thị Lan", "task": "Chuẩn bị phần demo", "due_date": None, "self_claimed": True},
            ],
        },
    )
    if with_echo:
        write_json(
            folder / "echo_eval.json",
            {
                "note": "Gán `is_echo: true/false` cho TỪNG câu bằng cách nghe track (true = mic thu lại tiếng loa ngoài của người khác). `null` = chưa gán.",
                "segments": [
                    {"start": 0.0, "end": 3.5, "text": "Lan làm slide báo cáo, gửi trước thứ Sáu tuần này nhé.", "speaker_id": 1, "speaker": "Nguyễn Văn Nam", "track_id": 1, "rms": 0.15, "is_echo": None},
                    {"start": 0.4, "end": 3.7, "text": "làm slide báo cáo gửi trước thứ sáu tuần này nhé", "speaker_id": 2, "speaker": "Trần Thị Lan", "track_id": 2, "rms": 0.02, "is_echo": None},
                ],
            },
        )
    print(f"Đã tạo khung dữ liệu MẪU tại: {folder}")
    print("  → Thay nội dung mẫu bằng dữ liệu thật, chép ghi âm thành `meeting.wav`/`.webm`, rồi đặt `\"annotated\": true`.")


def _ts(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def export_from_db(meeting_id: int, out_folder: Path) -> None:
    """Xuất 1 cuộc họp MeetFlow theo quy trình gán nhãn mù (xem docstring đầu file)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models import Meeting, MeetingRoom, WorkspaceMember
    from app.services import meeting_service, room_service

    s = load_backend_settings()
    engine = create_engine(s.DATABASE_URL)
    if out_folder.exists() and any(out_folder.iterdir()):
        raise SystemExit(f"Thư mục đích đã có dữ liệu (tránh ghi đè nhãn đã gán): {out_folder}")
    out_folder.mkdir(parents=True, exist_ok=True)

    with Session(engine) as db:
        m = db.get(Meeting, meeting_id)
        if m is None:
            raise SystemExit(f"Không tìm thấy cuộc họp id={meeting_id} trong CSDL.")
        is_online = m.source_type == "online"

        # 1. Ghi âm chính
        audio = meeting_service.audio_abspath(m)
        if audio and audio.exists():
            shutil.copy2(audio, out_folder / f"meeting{audio.suffix.lower()}")

        # 2. Thành viên nhóm + biệt danh (dữ liệu cấu hình, không phải đầu ra AI)
        ws_members = db.scalars(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == m.workspace_id).order_by(WorkspaceMember.joined_at)
        ).all()
        members_json = [{"id": wm.user_id, "full_name": wm.user.full_name, "nicknames": list(wm.nicknames or [])} for wm in ws_members]

        room = db.scalar(select(MeetingRoom).where(MeetingRoom.meeting_id == m.id)) if is_online else None
        tracks = list(room.tracks) if room and room.tracks else []
        guests = sorted({t.speaker_name for t in tracks if t.user_id is None and t.speaker_name})

        # 3. Template RỖNG cho người gán nhãn
        (out_folder / "reference.txt").write_text("", encoding="utf-8")
        if is_online:
            (out_folder / "reference_speakers.txt").write_text("", encoding="utf-8")
        write_json(
            out_folder / "expected_tasks.json",
            {
                "meeting_date": m.meeting_date.isoformat(),
                "source": m.source_type,
                "synthetic": False,
                "annotated": False,
                "members": members_json,
                "guests": guests,
                "tasks": [],
            },
        )

        # 4. Đầu ra CỦA HỆ THỐNG → file riêng, chỉ mở sau khi gán nhãn xong
        tr = m.transcript
        segs = list(tr.segments) if tr and tr.segments else []
        name_by_id = {wm.user_id: wm.user.full_name for wm in ws_members}
        write_json(
            out_folder / "system_output.json",
            {
                "WARNING": "ĐẦU RA CỦA HỆ THỐNG — KHÔNG mở trước khi gán nhãn xong reference*.txt / expected_tasks.json / echo_eval.json",
                "meeting_id": m.id,
                "stt_model": tr.stt_model if tr else None,
                "transcript_segments": segs,
                "transcript_full_text": tr.full_text if tr else None,
                "extracted_tasks": [
                    {
                        "title": et.title,
                        "assignee": name_by_id.get(et.assignee_id) if et.assignee_id else (et.assignee_name or et.raw_assignee),
                        "raw_assignee": et.raw_assignee,
                        "assignee_match": et.assignee_match,
                        "due_date": et.due_date.isoformat() if et.due_date else None,
                        "due_text": et.due_text,
                        "evidence_quote": et.evidence_quote,
                        "status": str(et.status),
                    }
                    for et in m.extracted_tasks
                ],
                "track_segments": {str(t.id): list(t.segments or []) for t in tracks},
            },
        )

        # 5. online_segments.json — chỉ Online Meeting thật có nhãn người nói
        if is_online and any(seg.get("speaker_id") is not None for seg in segs):
            write_json(out_folder / "online_segments.json", {"meeting_id": m.id, "stt_model": tr.stt_model if tr else None, "segments": segs})

        # 6. Track riêng + echo_eval.json (nhãn để trống — gán mù bằng cách nghe track)
        if tracks:
            t_dir = out_folder / "tracks"
            t_dir.mkdir(exist_ok=True)
            tracks_meta = []
            unfiltered: list[dict[str, Any]] = []
            for t in tracks:
                tp = room_service.track_abspath(t)
                rel_name = None
                if tp and tp.exists():
                    rel_name = f"track_{t.id}_{t.user_id or 0}{tp.suffix.lower()}"
                    shutil.copy2(tp, t_dir / rel_name)
                offset = max(0.0, (t.started_at - room.recording_started_at).total_seconds()) if room and room.recording_started_at else 0.0
                tracks_meta.append(
                    {"track_id": t.id, "user_id": t.user_id, "speaker_name": t.speaker_name, "offset_sec": round(offset, 3), "started_at": _ts(t.started_at), "file": rel_name}
                )
                for seg in t.segments or []:
                    unfiltered.append(dict(seg, is_echo=None))
            write_json(t_dir / "tracks_meta.json", {"room_code": room.code if room else None, "tracks": tracks_meta})
            if unfiltered:
                unfiltered.sort(key=lambda x: (x.get("start") or 0.0, x.get("end") or 0.0))
                write_json(
                    out_folder / "echo_eval.json",
                    {
                        "note": "Các câu TRƯỚC khi lọc vọng. Nghe track trong tracks/ rồi gán `is_echo: true` (mic thu lại loa ngoài) hoặc `false` cho TỪNG câu. Không xem system_output.json khi gán.",
                        "segments": unfiltered,
                    },
                )

    engine.dispose()
    print(f"Đã xuất cuộc họp #{meeting_id} ra: {out_folder}")
    print("  QUY TRÌNH GÁN NHÃN MÙ:")
    print("   1. Nghe ghi âm → gõ reference.txt (và reference_speakers.txt nếu là Online Meeting), giữ chữ hoa tên riêng.")
    print("   2. Điền `tasks` trong expected_tasks.json (đánh dấu `self_claimed` khi người nói tự nhận việc).")
    print("   3. Nghe từng track → gán `is_echo` true/false trong echo_eval.json.")
    print("   4. Đặt `\"annotated\": true`. CHỈ SAU ĐÓ mới được mở system_output.json / online_segments.json.")


def run_validate(target: Path) -> int:
    cases = discover_meetings(target)
    print(f"Kiểm tra {len(cases)} cuộc họp trong `{target}`:\n")
    tn1 = tn2 = tn4a = tn4b = 0
    total_errors = total_warnings = 0
    for c in cases:
        errors, warnings = validate_meeting(c.folder)
        real = not c.synthetic
        ok_tn1 = real and c.has_audio and c.has_reference
        ok_tn2 = real and c.has_expected_tasks and (c.has_reference or c.has_speaker_reference)
        ok_tn4a = real and c.has_expected_tasks and (c.has_speaker_reference or c.has_online_segments)
        ok_tn4b = real and c.echo_eval_path is not None and not any("is_echo" in w for w in warnings)
        tn1 += int(ok_tn1)
        tn2 += int(ok_tn2)
        tn4a += int(ok_tn4a)
        tn4b += int(ok_tn4b)
        badges = " ".join(tag for flag, tag in [(ok_tn1, "TN1/3"), (ok_tn2, "TN2"), (ok_tn4a, "TN4A"), (ok_tn4b, "TN4B")] if flag)
        sc_count = sum(1 for t in c.expected_tasks if t.get("self_claimed"))
        flags = " [GIẢ LẬP]" if c.synthetic else ""
        flags += " [CHƯA GÁN NHÃN]" if not c.annotated else ""
        print(f"  [{c.meeting_id}]{flags} [{badges or 'CHƯA ĐỦ'}] {len(c.members)} thành viên | {len(c.expected_tasks)} đầu việc ({sc_count} tự nhận)")
        for msg in errors:
            total_errors += 1
            print(f"      LỖI: {msg}")
        for msg in warnings:
            total_warnings += 1
            print(f"      cảnh báo: {msg}")

    print(
        f"\nSẵn sàng cho Chương 4 (không tính dữ liệu giả lập / chưa gán nhãn): TN1/TN3={tn1} | TN2={tn2} | "
        f"TN4A={tn4a} | TN4B={tn4b}  —  {total_errors} lỗi, {total_warnings} cảnh báo"
    )
    return 0 if total_errors == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Tạo mẫu, xuất từ MeetFlow (gán nhãn mù) và kiểm tra bộ dữ liệu GĐ7")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--validate", nargs="?", const=str(DEFAULT_DATA_DIR), help="Kiểm tra hợp lệ thư mục dữ liệu")
    g.add_argument("--new", help="Tạo thư mục dữ liệu mẫu mới trong experiments/data/<tên>")
    g.add_argument("--export-meeting", type=int, help="Xuất cuộc họp có id này từ PostgreSQL MeetFlow (template rỗng + system_output.json)")
    ap.add_argument("--out", help="Thư mục đích khi dùng --export-meeting (mặc định experiments/data/meeting_<id>)")
    ap.add_argument("--with-echo", action="store_true", help="Tạo kèm file mẫu `echo_eval.json` khi dùng --new")
    args = ap.parse_args()

    if args.validate is not None:
        try:
            raise SystemExit(run_validate(Path(args.validate)))
        except (json.JSONDecodeError, ValueError) as e:
            raise SystemExit(f"LỖI khi đọc bộ dữ liệu: {e}") from e
    if args.new:
        target = Path(args.new) if Path(args.new).is_absolute() else DEFAULT_DATA_DIR / args.new
        create_template(target, with_echo=args.with_echo)
    elif args.export_meeting is not None:
        target = Path(args.out) if args.out else DEFAULT_DATA_DIR / f"meeting_{args.export_meeting:02d}"
        export_from_db(args.export_meeting, target)


if __name__ == "__main__":
    main()
