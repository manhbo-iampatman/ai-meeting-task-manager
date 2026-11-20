"""Test tự động cho bộ script thực nghiệm Giai đoạn 7 (`experiments/`).

Không cần GPU, không gọi Gemini/Ollama (dùng LLM giả). Cần PostgreSQL vì `conftest.py` của backend
tự dựng schema cho mọi test. Kiểm tra: chuẩn hóa WER hai phía + đếm tên viết hoa, nạp dataset (BOM,
cờ synthetic/annotated, nhãn người nói khách), luật ghép đầu việc (chữ số, tiêu đề ngắn, ghép tối ưu),
chỉ số strict / None / macro, 3 nhánh danh sách thành viên, hàng thất bại, cache chấm lại theo đáp án
mới, TN3 cùng tập cuộc họp, TN4B (dữ liệu thật đã gán nhãn + mô phỏng) và sinh biểu đồ.
"""

from datetime import date
import itertools
import json
from pathlib import Path
import random
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import common  # noqa: E402
import eval_extraction  # noqa: E402
import exp1_stt  # noqa: E402
import exp2_llm  # noqa: E402
import exp4_online  # noqa: E402
import plot_results  # noqa: E402
from app.ai.extraction import ExtractedItem, transcript_lines  # noqa: E402
from app.ai.llm.base import LLMError  # noqa: E402
from app.ai.postprocess.name_matching import MemberInfo  # noqa: E402

SUMMARY = {"topic": "Họp", "key_points": [], "decisions": [], "open_issues": []}


class _FakeLLM:
    """LLM giả: trả lần lượt `responses` (hết thì lặp lại phần tử cuối), ghi lại prompt đã nhận."""

    name = "fake/llm"
    max_input_chars = 100_000

    def __init__(self, responses):
        self.responses = list(responses)
        self.last_usage = {"input_tokens": 120, "output_tokens": 40}
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, system_prompt, user_prompt, schema):
        self.calls += 1
        self.prompts.append(user_prompt)
        if isinstance(self.responses[0], Exception):
            raise self.responses[0]
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _resp(*items):
    return {"summary": SUMMARY, "action_items": [{"priority": "medium", "due": "", **it} for it in items]}


def _item(title, uid=None, raw=None, due=None):
    return ExtractedItem(
        title=title, raw_assignee=raw, assignee_id=uid, assignee_match="exact" if uid else "none", assignee_score=100,
        assignee_candidates=[], due_text=None, due_date=due, due_approximate=False, priority="medium",
        evidence_quote="", evidence_found=True, evidence_segment=0, evidence_start=0.0,
    )


def _meeting(folder: Path, *, tasks, members=None, reference=None, speakers=None, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    if reference is not None:
        (folder / "reference.txt").write_text(reference, encoding="utf-8")
    if speakers is not None:
        (folder / "reference_speakers.txt").write_text(speakers, encoding="utf-8")
    common.write_json(
        folder / "expected_tasks.json",
        {
            "meeting_date": "2026-11-16",
            "members": members if members is not None else [
                {"id": 1, "full_name": "Nguyễn Văn Nam", "nicknames": ["Nam"]},
                {"id": 2, "full_name": "Trần Thị Lan", "nicknames": ["Lan", "Su"]},
            ],
            "tasks": tasks,
            **extra,
        },
    )
    return common.load_meeting(folder)


# ---------------------------------------------------------------------------
# 1. WER: chuẩn hóa số hai phía, tên riêng viết hoa
# ---------------------------------------------------------------------------


def test_number_normalization_both_sides_and_capitalised_names():
    assert common.number_to_vi(25) == "hai mươi lăm"
    assert common.number_to_vi(2026) == "hai nghìn không trăm hai mươi sáu"
    assert common.number_to_vi(1005) == "một nghìn không trăm lẻ năm"
    assert common.number_to_vi(2_500_000) == "hai triệu năm trăm nghìn"

    for ref, hyp in [
        ("hạn ngày hai mươi bốn", "hạn ngày 24"),
        ("một trăm linh năm người", "105 người"),
        ("hai nghìn người", "2.000 người"),
        ("hai ngàn người", "2000 người"),
        ("năm mươi phần trăm", "50%"),
        ("ngày hai mươi lăm tháng mười một", "ngày 25/11"),
        ("ba phẩy năm điểm", "3,5 điểm"),
        ("thứ tư tuần sau", "thứ 4 tuần sau"),
        ("họp lúc chín giờ ba mươi", "họp lúc 9h30"),
    ]:
        m = common.compute_wer_metrics(ref, hyp)
        assert m.wer_norm == 0.0, (ref, hyp, common.normalize_for_wer(hyp, True))
        assert m.wer_raw > 0.0

    members = [MemberInfo(1, "Nguyễn Văn Nam", ["Nam"]), MemberInfo(2, "Trần Thị Lan", ["Lan"])]
    ref = "Nam bảo Lan nộp báo cáo ngày hai mươi lăm tháng mười một."
    m_ok = common.compute_wer_metrics(ref, "Nam bảo Lan nộp báo cáo ngày 25 tháng 11.", members=members)
    assert m_ok.wer_norm == 0.0 and (m_ok.name_hits, m_ok.name_total, m_ok.name_accuracy) == (2, 2, 1.0)
    m_bad = common.compute_wer_metrics(ref, "Nom bảo Lan nộp báo cáo ngày 25 tháng 11.", members=members)
    assert (m_bad.name_hits, m_bad.name_total) == (1, 2)

    # "miền nam", "an toàn" là từ thường (không viết hoa) → không tính là tên thành viên
    mem2 = [MemberInfo(1, "Nguyễn Văn Nam", ["Nam"]), MemberInfo(2, "Trần Bình An", ["An"])]
    m3 = common.compute_wer_metrics("Nam đi công tác miền nam, đảm bảo an toàn.", "Nam đi công tác miền nam đảm bảo an toàn", mem2)
    assert (m3.name_hits, m3.name_total) == (1, 1)


# ---------------------------------------------------------------------------
# 2. Dataset: BOM, nhãn người nói, khách, synthetic, validate (lỗi vs cảnh báo)
# ---------------------------------------------------------------------------


def test_dataset_loading_bom_speaker_labels_guests_and_validation(tmp_path: Path):
    folder = tmp_path / "meeting_01"
    case = _meeting(
        folder,
        reference="Chốt lại: Lan viết chương hai.\nCòn phần anh, anh sẽ làm dữ liệu.\n",
        speakers="Nam: Chốt lại: Lan viết chương hai.\nNguyễn Văn Nam: Còn phần anh, anh sẽ làm dữ liệu.\n",
        tasks=[
            {"assignee": "Lan", "task": "Viết chương 2", "due_date": "2026-11-20"},
            {"assignee": "Nguyễn Văn Nam", "task": "Làm dữ liệu", "due_date": None, "self_claimed": True},
        ],
    )
    assert common.discover_meetings(tmp_path)[0].meeting_id == "meeting_01"

    plain = common.parse_transcript_segments(folder / "reference.txt", case.members, parse_speakers=True)
    assert plain[0]["text"] == "Chốt lại: Lan viết chương hai." and "speaker" not in plain[0]
    sp = common.parse_transcript_segments(folder / "reference_speakers.txt", case.members, parse_speakers=True)
    assert [(s["speaker"], s["speaker_id"], s["text"]) for s in sp] == [
        ("Nguyễn Văn Nam", 1, "Chốt lại: Lan viết chương hai."),
        ("Nguyễn Văn Nam", 1, "Còn phần anh, anh sẽ làm dữ liệu."),
    ]
    errors, warnings = common.validate_meeting(folder)
    assert errors == [] and any("âm thanh" in w for w in warnings)

    # BOM (Notepad / PowerShell 5.1) không làm hỏng việc nạp dữ liệu
    raw = (folder / "expected_tasks.json").read_text(encoding="utf-8")
    (folder / "expected_tasks.json").write_text(raw, encoding="utf-8-sig")
    (folder / "reference_speakers.txt").write_text("Nguyễn Văn Nam: Chào mọi người.\nThầy Hùng: Để thầy duyệt đề cương.\n", encoding="utf-8-sig")
    case = common.load_meeting(folder)
    assert case.meeting_date == date(2026, 11, 16) and case.roster_declared

    # Người nói không khớp thành viên → LỖI; nhãn vẫn bị tách khỏi nội dung để nhánh không-nhãn không bị lộ
    errors, _ = common.validate_meeting(folder)
    assert any("Thầy Hùng" in e for e in errors)
    segs = common.parse_transcript_segments(folder / "reference_speakers.txt", case.members)
    assert segs[1] == {"start": None, "end": None, "text": "Để thầy duyệt đề cương.", "speaker": "Thầy Hùng", "speaker_id": None}
    assert all("Hùng" not in line for line in transcript_lines(segs, with_speakers=False))

    data = json.loads(raw)
    data["guests"] = ["Thầy Hùng"]
    common.write_json(folder / "expected_tasks.json", data)
    assert common.validate_meeting(folder)[0] == []


def test_synthetic_and_unannotated_meetings_excluded_by_default(tmp_path: Path):
    tasks = [{"assignee": "Lan", "task": "Viết chương 2", "due_date": None}]
    _meeting(tmp_path / "real", tasks=tasks, reference="Lan viết chương hai.\n")
    _meeting(tmp_path / "tts", tasks=tasks, reference="Lan viết chương hai.\n", synthetic=True)
    _meeting(tmp_path / "todo", tasks=[], reference="", annotated=False)
    cases = common.discover_meetings(tmp_path)
    assert [c.meeting_id for c in common.select_cases(cases)] == ["real", "todo"]
    assert [c.meeting_id for c in common.select_cases(cases, include_synthetic=True)] == ["real", "todo", "tts"]
    assert {c.meeting_id for c in cases if c.has_expected_tasks} == {"real", "tts"}

    # Không khai báo `members` → danh sách bị suy ra từ đáp án → cảnh báo
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    common.write_json(legacy / "expected_tasks.json", {"meeting_date": "2026-11-16", "tasks": tasks})
    assert not common.load_meeting(legacy).roster_declared
    assert any("members" in w for w in common.validate_meeting(legacy)[1])


# ---------------------------------------------------------------------------
# 3. Ghép đầu việc: chữ số, tiêu đề ngắn, ghép tối ưu
# ---------------------------------------------------------------------------


def test_title_rules_digits_spelled_numbers_dates_and_short_titles():
    ts = eval_extraction.title_score
    assert ts("Viết chương 2", "Viết chương 3") is None
    assert ts("Viết chương 2 cơ sở lý thuyết", "Viết chương 3 cơ sở lý thuyết") is None
    assert ts("Viết chương 2", "Viết chương hai") is not None
    assert ts("Chuẩn bị dữ liệu gồm 10 đoạn ghi âm", "Chuẩn bị dữ liệu gồm mười đoạn ghi âm") is not None
    assert ts("Nộp báo cáo", "Nộp báo cáo trước 25/11") is not None  # số trong ngày giờ không tính
    assert ts("Nộp báo cáo", "Nộp báo cáo trước thứ hai") is not None
    assert ts("Hoàn thành trình phát âm thanh", "Hoàn thành chương 1") is None
    # Tiêu đề ≤ 2 từ phải gần nguyên văn
    assert ts("Làm slide báo cáo", "Làm") is None
    assert ts("Gửi email hẹn lịch demo với thầy hướng dẫn", "Gửi email") is None
    assert ts("Làm slide", "làm slide.") is not None


def test_optimal_matching_beats_greedy_and_breaks_ties_by_assignee():
    members = [MemberInfo(1, "Trần Thị Lan", ["Lan"]), MemberInfo(2, "Lê Quang Minh", ["Minh"])]
    # Tham lam ghép "Gửi email cho thầy hướng dẫn"↔"Gửi email" (100 điểm) rồi bỏ sót đáp án thứ 2; tối ưu ghép đủ 2 cặp
    expected = [
        {"assignee": "Lan", "task": "Gửi email cho thầy hướng dẫn", "due_date": None},
        {"assignee": "Lan", "task": "Gửi email báo cáo", "due_date": None},
    ]
    pred = [_item("Gửi email báo cáo", 1), _item("Liên hệ thầy hướng dẫn qua email", 1)]
    pairs = eval_extraction.match_tasks(expected, pred, members)
    assert sorted((e["task"], p.title) for e, p, _ in pairs) == [
        ("Gửi email báo cáo", "Gửi email báo cáo"),
        ("Gửi email cho thầy hướng dẫn", "Liên hệ thầy hướng dẫn qua email"),
    ]

    # Trùng hệt tiêu đề, khác người làm → ghép đúng người (không ghép chéo)
    expected2 = [
        {"assignee": "Lan", "task": "Làm slide thuyết trình", "due_date": "2026-11-20"},
        {"assignee": "Minh", "task": "Làm slide thuyết trình", "due_date": "2026-11-20"},
    ]
    pred2 = [_item("Làm slide thuyết trình", 2, "Minh", date(2026, 11, 20)), _item("Làm slide thuyết trình", 1, "Lan", date(2026, 11, 20))]
    pairs2 = eval_extraction.match_tasks(expected2, pred2, members)
    assert len(pairs2) == 2 and all(eval_extraction.assignee_matches(e["assignee"], p, members) for e, p, _ in pairs2)

    # Thuật toán Hungary == vét cạn trên ma trận ngẫu nhiên nhỏ
    rng = random.Random(7)
    for _ in range(150):
        n, m = rng.randint(1, 4), rng.randint(1, 4)
        w = [[(rng.random() < 0.6) * rng.randint(1, 10**6) for _ in range(m)] for _ in range(n)]
        got = sum(w[i][j] for i, j in eval_extraction._hungarian_max(w))
        best = 0
        for k in range(1, min(n, m) + 1):
            for rows in itertools.combinations(range(n), k):
                for cols in itertools.permutations(range(m), k):
                    if all(w[r][c] for r, c in zip(rows, cols, strict=True)):
                        best = max(best, sum(w[r][c] for r, c in zip(rows, cols, strict=True)))
        assert got == best


# ---------------------------------------------------------------------------
# 4. Chấm 1 cuộc họp: nhãn người nói, việc tự nhận, strict, None, macro
# ---------------------------------------------------------------------------


def test_evaluate_case_speakers_self_claimed_strict_and_conventions(tmp_path: Path):
    case = _meeting(
        tmp_path / "m1",
        speakers="Nguyễn Văn Nam: Lan viết chương hai trước thứ Sáu tuần này nhé.\nNguyễn Văn Nam: Còn phần anh, anh sẽ làm bộ dữ liệu.\n",
        tasks=[
            {"assignee": "Trần Thị Lan", "task": "Viết chương 2", "due_date": "2026-11-20", "self_claimed": False},
            {"assignee": "Nguyễn Văn Nam", "task": "Làm bộ dữ liệu", "due_date": None, "self_claimed": True},
        ],
    )
    t1 = {"task": "Viết chương 2", "assignees": ["Lan"], "due": "thứ Sáu tuần này", "evidence": "Lan viết chương hai trước thứ Sáu tuần này nhé."}
    r_no = eval_extraction.evaluate_case(
        _FakeLLM([_resp(t1, {"task": "Làm bộ dữ liệu", "assignees": ["anh"], "evidence": "Còn phần anh, anh sẽ làm bộ dữ liệu."})]),
        case, use_speakers=False, prefer_speakers=True,
    )
    assert (r_no["tp"], r_no["assignee_correct"], r_no["self_claimed_correct"], r_no["self_left_blank"]) == (2, 1, 0, 1)
    assert (r_no["assignee_blank"], r_no["assignee_wrong"], r_no["self_claimed_blank"], r_no["strict_tp"]) == (1, 0, 1, 1)
    assert r_no["matches"][0]["title_score"] == 100 and r_no["sensitivity_tp"]["80"] == 2

    r_yes = eval_extraction.evaluate_case(
        _FakeLLM([_resp(t1, {"task": "Làm bộ dữ liệu", "assignees": ["Nguyễn Văn Nam"], "evidence": "Còn phần anh, anh sẽ làm bộ dữ liệu."})]),
        case, use_speakers=True, prefer_speakers=True,
    )
    assert (r_yes["tp"], r_yes["assignee_correct"], r_yes["self_claimed_correct"], r_yes["speaker_matched"], r_yes["strict_tp"]) == (2, 2, 1, 1, 2)

    # Cuộc họp không có đầu việc nào: P/R/F1/độ đúng = None và bị loại khỏi Macro
    empty = _meeting(tmp_path / "m0", tasks=[], reference="Hôm nay chỉ cập nhật tình hình.\n")
    r_empty = eval_extraction.evaluate_case(_FakeLLM([_resp()]), empty)
    assert (r_empty["precision"], r_empty["recall"], r_empty["f1"], r_empty["assignee_acc"]) == (None, None, None, None)

    agg = eval_extraction.aggregate_extraction_runs("test", [r_no, r_yes, r_empty])
    assert agg["meetings_count"] == 3 and agg["macro_meetings_count"] == 2
    assert agg["micro_f1"] == 1.0 and agg["macro_f1"] == 1.0 and agg["assignee_acc"] == 0.75
    assert agg["strict_f1"] == 0.75 and agg["self_claimed_recall"] == 0.5
    assert agg["due_with_date_acc"] == 1.0 and agg["spurious_due_rate"] == 0.0
    lo, hi = agg["strict_f1_ci95"]
    assert 0.0 <= lo <= agg["strict_f1"] <= hi <= 1.0
    assert agg["threshold_sensitivity"]["60"]["f1"] == 1.0


def test_member_arms_prompt_only_vs_none(tmp_path: Path):
    case = _meeting(
        tmp_path / "m1",
        reference="Su làm slide báo cáo nhé.\n",
        tasks=[{"assignee": "Trần Thị Lan", "task": "Làm slide báo cáo", "due_date": None}],
    )

    def run(mode, name):
        llm = _FakeLLM([_resp({"task": "Làm slide báo cáo", "assignees": [name], "evidence": "Su làm slide báo cáo nhé."})])
        row = eval_extraction.evaluate_case(llm, case, member_mode=mode)
        return row, llm.prompts[0]

    full, p_full = run("full", "Su")
    prompt_only, p_po = run("prompt_only", "Su")
    none, _ = run("none", "Su")
    none_real_name, _ = run("none", "chị Lan")
    assert "Thành viên nhóm" in p_full and "Thành viên nhóm" not in p_po
    assert full["assignee_correct"] == 1 and prompt_only["assignee_correct"] == 1  # hậu xử lý vẫn ghép biệt danh
    assert none["assignee_correct"] == 0 and none["assignee_wrong"] == 1  # members=[] → biệt danh không ghép được
    assert none_real_name["assignee_correct"] == 1  # tên gọi thật vẫn được tính đúng


def test_llm_output_error_is_failure_row_but_network_error_aborts(tmp_path: Path):
    case = _meeting(tmp_path / "m1", reference="Lan làm slide.\n", tasks=[{"assignee": "Lan", "task": "Làm slide", "due_date": None}])
    bad = {"summary": SUMMARY, "action_items": [{"assignees": ["Lan"]}]}  # thiếu `task` → sai cấu trúc 2 lần
    row = eval_extraction.evaluate_case(_FakeLLM([bad, bad]), case)
    assert row["failed"] and (row["tp"], row["fn"], row["predicted_count"]) == (0, 1, 0)
    with pytest.raises(LLMError):
        eval_extraction.evaluate_case(_FakeLLM([LLMError("Không kết nối được Gemini API (ConnectError).")]), case)


# ---------------------------------------------------------------------------
# 5. Cache phản hồi thô: chấm lại theo đáp án mới, khóa theo bản ghi / run-id
# ---------------------------------------------------------------------------


def test_cache_rescores_against_changed_gold_without_new_llm_calls(tmp_path: Path):
    data = tmp_path / "data"
    folder = data / "m1"
    _meeting(folder, reference="Lan viết chương hai nhé.\n", tasks=[{"assignee": "Lan", "task": "Làm slide", "due_date": None}])
    fake = _FakeLLM([_resp({"task": "Viết chương 2", "assignees": ["Lan"], "evidence": "Lan viết chương hai nhé."})])
    kw = dict(label="gemini/x", provider="gemini", model="x", member_mode="full", cache_dir=tmp_path / "cache",
              skip_existing=True, sleep_sec=0, allow_fallback=False, llm_factory=lambda: fake)

    r1 = exp2_llm.run_config_on_cases(cases=common.discover_meetings(data), **kw)
    assert r1["micro_f1"] == 0.0 and fake.calls == 1

    gold = json.loads((folder / "expected_tasks.json").read_text(encoding="utf-8"))
    gold["tasks"][0]["task"] = "Viết chương 2"  # người gán nhãn sửa đáp án
    common.write_json(folder / "expected_tasks.json", gold)
    r2 = exp2_llm.run_config_on_cases(cases=common.discover_meetings(data), **kw)
    assert r2["micro_f1"] == 1.0 and fake.calls == 1  # chấm lại, KHÔNG gọi lại LLM
    assert r2["per_meeting"][0]["from_cache"]

    exp2_llm.run_config_on_cases(cases=common.discover_meetings(data), **{**kw, "run_id": "r2"})
    assert fake.calls == 2  # run-id khác → lần chạy độc lập
    (folder / "reference.txt").write_text("Lan viết chương hai nhé, trước thứ Sáu.\n", encoding="utf-8")
    exp2_llm.run_config_on_cases(cases=common.discover_meetings(data), **kw)
    assert fake.calls == 3  # bản ghi đổi → khóa cache đổi


def test_tn3_compares_gold_and_stt_on_same_meeting_set(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    for mid, n_tasks in (("m1", 1), ("m2", 3)):
        _meeting(
            data / mid,
            reference="Lan viết chương hai nhé.\n",
            tasks=[{"assignee": "Lan", "task": f"Viết chương 2 phần {k}" if k else "Viết chương 2", "due_date": None} for k in range(n_tasks)],
        )
    sdir = tmp_path / "stt" / "faster-whisper__small__prompt"
    sdir.mkdir(parents=True)
    (sdir / "m1.txt").write_text("Lan viết chương hai nhé.\n", encoding="utf-8")
    fake = _FakeLLM([_resp({"task": "Viết chương 2", "assignees": ["Lan"], "evidence": "Lan viết chương hai nhé."})])
    monkeypatch.setattr(exp2_llm, "build_llm", lambda *a, **k: fake)
    monkeypatch.setattr(sys, "argv", ["exp2_llm.py", "--data", str(data), "--models", "gemini:x", "--stt-dirs", str(sdir), "--sleep", "0", "--out-dir", str(tmp_path / "res")])
    exp2_llm.main()

    comp = json.loads((tmp_path / "res" / "exp3_e2e.json").read_text(encoding="utf-8"))["groups"][0]["comparisons"][0]
    assert comp["gold"]["meetings_count"] == 1 and comp["stt"]["meetings_count"] == 1
    assert comp["deltas"]["f1"]["delta"] == 0.0 and comp["deltas"]["assignee_acc"]["delta"] == 0.0


# ---------------------------------------------------------------------------
# 6. TN4B: dữ liệu thật đã gán nhãn + phân tích độ nhạy mô phỏng
# ---------------------------------------------------------------------------


def _echo_segments(label):
    return [
        {"start": 0.0, "end": 3.0, "text": "Lan làm slide báo cáo gửi trước thứ Sáu nhé", "speaker_id": 1, "speaker": "Nam", "track_id": 1, "rms": 0.10, "is_echo": False if label else None},
        {"start": 0.3, "end": 3.2, "text": "làm slide báo cáo gửi trước thứ sáu nhé", "speaker_id": 2, "speaker": "Lan", "track_id": 2, "rms": 0.02, "is_echo": True if label else None},
        {"start": 10.0, "end": 13.0, "text": "Em sẽ cập nhật bảng công việc hôm nay", "speaker_id": 2, "speaker": "Lan", "track_id": 2, "rms": 0.08, "is_echo": False if label else None},
    ]


def test_echo_real_data_requires_labels_and_synthetic_sensitivity(tmp_path: Path):
    for mid, labelled in (("a_labelled", True), ("b_unlabelled", False)):
        (tmp_path / mid).mkdir()
        common.write_json(tmp_path / mid / "echo_eval.json", {"segments": _echo_segments(labelled)})
    datasets = exp4_online.labelled_echo_datasets(common.discover_meetings(tmp_path), verbose=False)
    assert [mid for mid, _ in datasets] == ["a_labelled"]  # câu `is_echo: null` = chưa gán nhãn → bỏ qua

    v1 = exp4_online.score_echo_dataset(datasets, "v1_raw_rms")
    assert (v1["tp"], v1["fp"], v1["fn"], v1["tn"], v1["echo_f1"]) == (1, 0, 0, 2, 1.0)
    cur = exp4_online.score_echo_dataset(datasets, "current", similarity=exp4_online.production_similarity(), with_ci=True)
    assert cur["tp"] + cur["fp"] + cur["fn"] + cur["tn"] == 3  # bộ lọc hiện tại = hộp đen, chỉ kiểm tra hợp lệ

    kw = dict(echo_levels=(0.1, 0.6), gains=(1.0, 10.0), reps=2)
    syn = exp4_online.build_synthetic_sensitivity(**kw)
    assert syn == exp4_online.build_synthetic_sensitivity(**kw)  # hạt giống cố định → tái lập
    assert len(syn) == 2 * 2 * 2
    for r in syn:
        for k in ("echo_precision", "echo_recall", "echo_f1", "false_drop_rate"):
            assert r[k] is None or 0.0 <= r[k] <= 1.0
    by = {(r["echo_level"], r["gain_ratio"], r["mode"]): r for r in syn}
    assert by[(0.1, 1.0, "v1_raw_rms")]["false_drop_rate"] == 0.0
    assert by[(0.6, 10.0, "v1_raw_rms")]["false_drop_rate"] > 0.0  # mốc v1: vọng to hơn giọng thật → xóa nhầm


# ---------------------------------------------------------------------------
# 7. Xuất báo cáo + biểu đồ từ kết quả thật của pipeline (LLM giả)
# ---------------------------------------------------------------------------


def test_exports_and_all_charts(tmp_path: Path):
    data = tmp_path / "data"
    for mid in ("m1", "m2"):
        _meeting(
            data / mid,
            reference="Lan viết chương hai trước thứ Sáu nhé.\nCòn phần anh, anh sẽ làm bộ dữ liệu.\n",
            speakers="Nguyễn Văn Nam: Lan viết chương hai trước thứ Sáu nhé.\nNguyễn Văn Nam: Còn phần anh, anh sẽ làm bộ dữ liệu.\n",
            tasks=[
                {"assignee": "Trần Thị Lan", "task": "Viết chương 2", "due_date": "2026-11-20"},
                {"assignee": "Nguyễn Văn Nam", "task": "Làm bộ dữ liệu", "due_date": None, "self_claimed": True},
            ],
        )
    cases = common.discover_meetings(data)
    fake = _FakeLLM([_resp(
        {"task": "Viết chương 2", "assignees": ["Lan"], "due": "thứ Sáu tuần này", "evidence": "Lan viết chương hai trước thứ Sáu nhé."},
        {"task": "Làm bộ dữ liệu", "assignees": ["anh"], "evidence": "Còn phần anh, anh sẽ làm bộ dữ liệu."},
    )])
    res = tmp_path / "results"
    kw = dict(provider="gemini", model="x", cases=cases, cache_dir=res / "cache", skip_existing=True, sleep_sec=0, allow_fallback=False, llm_factory=lambda: fake)
    runs = [exp2_llm.run_config_on_cases(label=f"gemini/x{eval_extraction.MEMBER_MODE_LABELS[m]}", member_mode=m, **kw) for m in eval_extraction.MEMBER_MODES]
    exp2_llm.export_exp2_reports(runs, res)
    gold = runs[0]
    stt = exp2_llm.run_config_on_cases(label="gemini/x + STT", member_mode="full", **{**kw, "cases": cases[:1]})
    gold_same = exp2_llm.restrict_run(gold, {"m1"})
    exp2_llm.export_exp3_reports([{"llm": "gemini/x", "comparisons": [{"stt_source": "faster-whisper__small__prompt", "gold": gold_same, "stt": stt, "deltas": exp2_llm.e2e_deltas(gold_same, stt)}]}], res)
    groups = exp4_online.run_speaker_ablation(models=["gemini:x"], cases=cases, cache_dir=res / "cache", skip_existing=True, sleep_sec=0, allow_fallback=False, llm_factory=lambda: fake)
    assert groups[0]["deltas"]["f1"]["meetings"] == 2
    exp4_online.export_exp4_speakers(groups, res)

    (data / "m1" / "echo_eval.json").write_text(json.dumps({"segments": _echo_segments(True)}), encoding="utf-8")
    labelled = exp4_online.labelled_echo_datasets(common.discover_meetings(data), verbose=False)
    headline = [exp4_online.score_echo_dataset(labelled, m, exp4_online.production_similarity(), with_ci=True) for m in exp4_online.MODES]
    sweep = [exp4_online.score_echo_dataset(labelled, m, th) for th in (70, 80, 90) for m in exp4_online.MODES]
    exp4_online.export_exp4_echo(headline, sweep, exp4_online.build_synthetic_sensitivity((0.1, 0.5), (1.0, 4.0, 10.0), reps=1), res)

    wer = common.compute_wer_metrics("Nam làm việc", "Nom làm việc", [MemberInfo(1, "Nam", [])]).to_dict()
    row = {"meeting_id": "m1", "duration_sec": 60.0, "processing_sec": 4.0, "dropped_count": 0, "prompt_echo": False, "wer": wer}
    exp1_stt.export_exp1_reports(
        [exp1_stt.aggregate_stt_runs("faster-whisper/small", up, [row], {"baseline_mb": 400, "peak_mb": 900, "delta_mb": 500}) for up in (False, True)],
        res,
        failed=[{"spec": "hf:vinai/PhoWhisper-small", "error": "RuntimeError: thiếu torch"}],
    )
    assert "PhoWhisper" in (res / "exp1_stt.md").read_text(encoding="utf-8")

    charts = plot_results.generate_all_charts(res)
    assert {p.name for p in charts} == {
        "chart1_stt_wer_speed.png",
        "chart1b_stt_prompt_effect.png",
        "chart2_llm_comparison.png",
        "chart2b_match_threshold_sensitivity.png",
        "chart3_e2e_propagation.png",
        "chart4a_speaker_labels.png",
        "chart4b_echo_real.png",
        "chart4c_echo_synthetic_sensitivity.png",
    }
    assert all(p.stat().st_size > 10_000 for p in charts)
