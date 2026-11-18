"""Nói chuyện với LiveKit — máy chủ phòng họp (WebRTC) của "Online Meeting".

LiveKit là một SFU (Selective Forwarding Unit): mỗi người gửi hình / tiếng của mình lên máy
chủ MỘT lần, máy chủ chuyển tiếp cho những người còn lại. (Nếu ai cũng gửi thẳng cho từng
người khác — kiểu "mesh" — thì 6 người cần 30 luồng, máy yếu không chịu nổi.)

Backend MeetFlow KHÔNG xử lý hình / tiếng. Nó chỉ làm 2 việc:

1. CẤP VÉ (token) cho trình duyệt vào phòng. Vé là một JWT ký bằng khóa bí mật mà chỉ
   backend và LiveKit biết → LiveKit tin "người cầm vé này là user 12, được vào phòng abc"
   mà không cần hỏi lại backend. Nhờ vậy quyền vào phòng do MeetFlow quyết định (phải đăng
   nhập, phải là thành viên nhóm).

2. QUẢN LÝ PHÒNG qua API của LiveKit (tạo phòng, xóa phòng = mời mọi người ra, đếm người,
   ghi "đang ghi âm" vào thông tin phòng). API này theo chuẩn Twirp: gửi POST kèm JSON.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.core.config import get_settings

log = logging.getLogger(__name__)

JOIN_TOKEN_TTL = timedelta(hours=12)  # vé chỉ được kiểm tra lúc kết nối (và khi tự kết nối lại)


class LiveKitError(Exception):
    """Không gọi được LiveKit (chưa bật Docker, sai khóa...)."""


def _sign(claims: dict[str, Any], ttl: timedelta) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"iss": s.LIVEKIT_API_KEY, "nbf": now - timedelta(seconds=10), "exp": now + ttl, **claims}
    return jwt.encode(payload, s.LIVEKIT_API_SECRET, algorithm="HS256")


def create_join_token(room: str, user_id: int, display_name: str) -> str:
    """Vé cho MỘT người vào MỘT phòng: được gửi mic / cam / màn hình và nhận của người khác."""
    return _sign(
        {
            "sub": str(user_id),  # "identity" trong LiveKit = id tài khoản MeetFlow
            "name": display_name,
            "video": {
                "roomJoin": True,
                "room": room,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": False,  # không có chat
            },
        },
        JOIN_TOKEN_TTL,
    )


class LiveKitAPI:
    """Các lệnh quản lý phòng mà backend cần. Test thay lớp này bằng bản giả (không cần Docker)."""

    def _call(self, method: str, body: dict[str, Any], room: str | None = None) -> dict[str, Any]:
        grant: dict[str, Any] = {"roomCreate": True, "roomList": True, "roomAdmin": True}
        if room:
            grant["room"] = room
        token = _sign({"sub": "meetflow-backend", "video": grant}, timedelta(minutes=5))
        url = f"{get_settings().LIVEKIT_URL.rstrip('/')}/twirp/livekit.RoomService/{method}"
        try:
            r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
        except httpx.HTTPError as e:
            raise LiveKitError(f"Không kết nối được LiveKit ở {get_settings().LIVEKIT_URL}: {e}") from e
        if r.status_code == 404 and method != "CreateRoom":
            return {"not_found": True}  # phòng đã bị LiveKit đóng
        if r.status_code >= 400:
            raise LiveKitError(f"LiveKit từ chối {method}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.content else {}

    def create_room(self, name: str, metadata: dict[str, Any]) -> None:
        s = get_settings()
        self._call(
            "CreateRoom",
            {
                "name": name,
                "max_participants": s.ROOM_MAX_PARTICIPANTS,
                "empty_timeout": 600,
                "departure_timeout": max(300, s.ROOM_EMPTY_CLOSE_SEC + 120),
                "metadata": json.dumps(metadata),
            },
        )

    def delete_room(self, name: str) -> None:
        """Đóng phòng: mọi người đang ở trong bị ngắt kết nối ("Kết thúc cho mọi người")."""
        self._call("DeleteRoom", {"room": name})

    def participant_ids(self, name: str) -> list[int] | None:
        """Id tài khoản của những người đang ở trong phòng, XẾP THEO THỨ TỰ VÀO PHÒNG (ai vào trước
        đứng trước — dùng để chọn chủ phòng mới). None = LiveKit không còn phòng này."""
        data = self._call("ListParticipants", {"room": name}, room=name)
        if data.get("not_found"):
            return None
        people: list[tuple[int, int]] = []  # (thời điểm vào phòng, id tài khoản)
        for p in data.get("participants") or []:
            try:
                people.append((int(p.get("joined_at") or 0), int(p.get("identity", ""))))
            except ValueError:
                continue
        return [uid for _, uid in sorted(people)]

    def set_metadata(self, name: str, metadata: dict[str, Any]) -> None:
        """Ghi trạng thái ghi âm vào thông tin phòng → LiveKit báo ngay cho mọi trình duyệt trong phòng."""
        self._call("UpdateRoomMetadata", {"room": name, "metadata": json.dumps(metadata)}, room=name)


_api: LiveKitAPI | None = None


def get_livekit() -> LiveKitAPI:
    global _api
    if _api is None:
        _api = LiveKitAPI()
    return _api
