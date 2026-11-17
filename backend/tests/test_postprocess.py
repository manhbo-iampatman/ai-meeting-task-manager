"""Test hậu xử lý Giai đoạn 4: ghép tên (F15) và đổi hạn chót thành ngày (F16). Không cần CSDL hay AI."""

from datetime import date

import pytest

from app.ai.postprocess.name_matching import MemberInfo, match_name, split_assignees
from app.ai.postprocess.vi_date_parser import parse_due

MONDAY = date(2026, 11, 16)  # ngày họp mẫu: thứ Hai 16/11/2026


# ---------------- F16: ngày ----------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Thứ trong tuần
        ("thứ Sáu tuần này", date(2026, 11, 20)),
        ("nộp trước thứ Sáu tuần này nhé", date(2026, 11, 20)),
        ("thứ Tư tuần sau", date(2026, 11, 25)),
        ("T4 tuần tới", date(2026, 11, 25)),
        ("sáng thứ Hai tuần sau", date(2026, 11, 23)),
        ("thứ năm tuần sau nữa", date(2026, 12, 3)),
        ("thứ 6", date(2026, 11, 20)),
        ("thứ hai", date(2026, 11, 23)),  # họp thứ Hai, nói "thứ Hai" = thứ Hai TUẦN SAU
        ("chủ nhật", date(2026, 11, 22)),
        # Ngày tuyệt đối
        ("ngày 25 tháng 11", date(2026, 11, 25)),
        ("ngày hai mươi lăm tháng mười một", date(2026, 11, 25)),
        ("25/11", date(2026, 11, 25)),
        ("20-11-2026", date(2026, 11, 20)),
        ("ngày mười lăm tháng mười hai năm 2026", date(2026, 12, 15)),
        ("ngày 20", date(2026, 11, 20)),
        ("ngày 5", date(2026, 12, 5)),  # ngày 5 đã qua trong tháng này → tháng sau
        ("mùng 5 tháng sau", date(2026, 12, 5)),
        ("ngày hai mươi mốt", date(2026, 11, 21)),  # "mốt" ở đây là số 1, không phải "ngày mốt"
        # Tương đối
        ("hôm nay", date(2026, 11, 16)),
        ("trong ngày mai luôn nhé", date(2026, 11, 17)),
        ("ngày kia", date(2026, 11, 18)),
        ("ngày mốt", date(2026, 11, 18)),
        ("3 ngày nữa", date(2026, 11, 19)),
        ("ba ngày nữa", date(2026, 11, 19)),
        ("hai tuần nữa", date(2026, 11, 30)),
    ],
)
def test_parse_due_exact(text, expected):
    r = parse_due(text, MONDAY)
    assert r.date == expected, r
    assert r.approximate is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Quy ước đã chốt: cuối tuần = Chủ nhật, đầu tuần = thứ Hai, cuối tháng = ngày cuối tháng
        ("cuối tuần này", date(2026, 11, 22)),
        ("cuối tuần", date(2026, 11, 22)),
        ("cuối tuần sau", date(2026, 11, 29)),
        ("đầu tuần sau", date(2026, 11, 23)),
        ("cuối tháng", date(2026, 11, 30)),
        ("cuối tháng sau", date(2026, 12, 31)),
        ("giữa tháng 12", date(2026, 12, 15)),
        ("trong tuần sau", date(2026, 11, 29)),
        ("cuối năm", date(2026, 12, 31)),
        ("ngày 5 tháng 1", date(2027, 1, 5)),  # tháng 1 đã qua → hiểu là năm sau
        ("ngày 10/11", date(2026, 11, 10)),  # vừa qua vài ngày → giữ nguyên nhưng đánh dấu cần kiểm tra
    ],
)
def test_parse_due_approximate_is_flagged(text, expected):
    r = parse_due(text, MONDAY)
    assert r.date == expected, r
    assert r.approximate is True  # giao diện sẽ nhắc người dùng kiểm tra lại


@pytest.mark.parametrize("text", ["", None, "càng sớm càng tốt", "sớm nhất có thể", "ngày 31 tháng 2", "khi nào rảnh"])
def test_parse_due_unknown_returns_none(text):
    assert parse_due(text, MONDAY).date is None  # không hiểu thì để trống, KHÔNG đoán bừa


def test_parse_due_uses_meeting_date_as_base():
    """Cùng câu "thứ Sáu tuần này" nhưng họp ở tuần khác thì ra ngày khác."""
    assert parse_due("thứ Sáu tuần này", date(2026, 12, 28)).date == date(2027, 1, 1)
    assert parse_due("ngày mai", date(2026, 12, 31)).date == date(2027, 1, 1)
    assert parse_due("cuối tháng", date(2028, 2, 10)).date == date(2028, 2, 29)  # năm nhuận


# ---------------- F15: tên ----------------

MEMBERS = [
    MemberInfo(1, "Nguyễn Văn Nam", ["Nam", "anh Nam"]),
    MemberInfo(2, "Trần Thị Lan", ["chị Lan"]),
    MemberInfo(3, "Lê Quang Minh", []),
]


@pytest.mark.parametrize(
    ("raw", "user_id", "method"),
    [
        ("Nam", 1, "exact"),
        ("anh Nam", 1, "exact"),
        ("Nguyễn Văn Nam", 1, "exact"),
        ("Lan", 2, "exact"),
        ("em Lan", 2, "exact"),  # bỏ từ xưng hô đứng trước tên
        ("LAN", 2, "exact"),  # Whisper viết hoa
        ("Minh", 3, "exact"),  # không có biệt danh vẫn khớp nhờ chữ cuối của họ tên
        ("Lân", 2, "no_accent"),  # sai dấu
        ("Min", 3, "fuzzy"),  # nghe thiếu chữ (lỗi thật ở Giai đoạn 3)
        ("Văn Nam", 1, "fuzzy"),
    ],
)
def test_match_name(raw, user_id, method):
    m = match_name(raw, MEMBERS)
    assert (m.user_id, m.method) == (user_id, method)


@pytest.mark.parametrize(
    ("raw", "method"),
    [
        ("Duy", "none"),  # không có trong nhóm → giữ dạng chữ (F20)
        ("Linh", "none"),  # gần giống "Minh" nhưng chưa đủ ngưỡng → không ghép bừa
        ("anh", "self"),  # người nói tự nhận việc → để trống, chờ duyệt
        ("em", "self"),
        ("mình", "self"),
        ("cả nhóm", "group"),
        ("", "none"),
        (None, "none"),
    ],
)
def test_match_name_unassigned(raw, method):
    m = match_name(raw, MEMBERS)
    assert m.user_id is None and m.method == method


def test_two_members_same_name_is_ambiguous():
    members = [MemberInfo(4, "Phạm Hoàng Nam"), MemberInfo(6, "Lê Nam")]
    m = match_name("Nam", members)
    assert m.user_id is None and m.method == "ambiguous" and m.candidates == [4, 6]
    # Gọi rõ hơn thì hết mơ hồ
    assert match_name("Hoàng Nam", members).user_id == 4


def test_declared_nickname_beats_derived_given_name():
    """Nhóm có 2 bạn tên Nam; bạn nào khai biệt danh "Nam" thì chữ "Nam" thuộc về bạn đó."""
    members = [MemberInfo(1, "Nguyễn Văn Nam", ["Nam"]), MemberInfo(4, "Phạm Hoàng Nam")]
    assert match_name("Nam", members).user_id == 1


def test_member_named_anh_is_not_treated_as_pronoun():
    members = [MemberInfo(5, "Nguyễn Tuấn Anh")]
    assert match_name("Anh", members).user_id == 5  # viết hoa → tên riêng
    assert match_name("anh", members).method == "self"  # viết thường → đại từ


def test_split_assignees():
    assert split_assignees("Lan và Minh") == ["Lan", "Minh"]
    assert split_assignees("Nam, Lan với Minh") == ["Nam", "Lan", "Minh"]
    assert split_assignees("anh Nam") == ["anh Nam"]
