"""Chuẩn bị chạy MeetFlow trong mạng LAN cho phòng "Online Meeting" (Giai đoạn 6).

Chạy lại mỗi khi máy đổi mạng (đổi Wi-Fi, phát hotspot...) vì IP của máy thay đổi:

    backend\\.venv\\Scripts\\python scripts\\setup_lan.py            # tự dò IP
    backend\\.venv\\Scripts\\python scripts\\setup_lan.py --ip 192.168.1.100

Script làm 3 việc:
  1. Tìm IP của máy trong mạng LAN.
  2. Ghi `.env` ở thư mục gốc (Docker Compose đọc) và cập nhật `backend/.env`:
     IP cho LiveKit + cặp khóa API dùng chung giữa LiveKit và backend.
  3. Tạo chứng chỉ HTTPS TỰ KÝ (`certs/lan-cert.pem`, `certs/lan-key.pem`) bằng OpenSSL.

Vì sao cần HTTPS? Trình duyệt chỉ cho trang web dùng camera / micro khi trang chạy trên
https:// (hoặc localhost). Máy khác trong LAN mở http://192.168.x.x sẽ KHÔNG bật được mic.

Vì sao "tự ký"? Chứng chỉ thật phải do một tổ chức (CA) cấp cho tên miền. Trong LAN ta tự
ký lấy → trình duyệt không tin sẵn, lần đầu phải bấm "Nâng cao → Vẫn tiếp tục". Kết nối
vẫn được mã hóa bình thường.
"""

import argparse
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "certs"
CERT, KEY, CERT_INFO = CERT_DIR / "lan-cert.pem", CERT_DIR / "lan-key.pem", CERT_DIR / "lan-cert.txt"


def detect_lan_ip() -> str:
    """IP mà máy dùng để ra mạng. Mở socket UDP "hướng" tới một địa chỉ ngoài rồi xem hệ điều
    hành chọn IP nguồn nào — KHÔNG có gói tin nào thật sự được gửi đi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def update_env(path: Path, values: dict[str, str], header: str = "") -> None:
    """Sửa / thêm các dòng KEY=VALUE, giữ nguyên mọi dòng khác (API key Gemini, ...)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else ([header] if header else [])
    left = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and key in left:
            lines[i] = f"{key}={left.pop(key)}"
    if left:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"{k}={v}" for k, v in left.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    for p in (  # Git for Windows có kèm OpenSSL
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files (x86)\Git\mingw64\bin\openssl.exe",
    ):
        if Path(p).exists():
            return p
    return None


def make_cert(ip: str) -> bool:
    """Tạo chứng chỉ tự ký có hiệu lực cho IP của máy + localhost. Trả về True nếu vừa tạo mới."""
    names = f"IP:{ip},IP:127.0.0.1,DNS:localhost"
    if CERT.exists() and KEY.exists() and CERT_INFO.exists() and CERT_INFO.read_text(encoding="utf-8").strip() == names:
        return False  # chứng chỉ cũ vẫn đúng IP → giữ lại (đỡ phải bấm chấp nhận lại trên từng máy)
    openssl = find_openssl()
    if openssl is None:
        sys.exit("Không tìm thấy OpenSSL. Cài Git for Windows (có kèm OpenSSL) rồi chạy lại.")
    CERT_DIR.mkdir(exist_ok=True)
    subprocess.run(
        [
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "365",
            "-keyout", str(KEY), "-out", str(CERT),
            "-subj", "/CN=MeetFlow LAN",
            # subjectAltName: trình duyệt so địa chỉ đang mở với danh sách này
            "-addext", f"subjectAltName={names}",
        ],
        check=True,
        capture_output=True,
    )
    CERT_INFO.write_text(names + "\n", encoding="utf-8")
    return True


def main() -> None:
    # Cửa sổ lệnh Windows mặc định không in được tiếng Việt có dấu → ép dùng UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Chuẩn bị chạy MeetFlow trong mạng LAN")
    ap.add_argument("--ip", help="IP của máy trong LAN (mặc định: tự dò)")
    args = ap.parse_args()
    ip = args.ip or detect_lan_ip()

    root_env, backend_env = ROOT / ".env", ROOT / "backend" / ".env"
    old = read_env(root_env)
    key = old.get("LIVEKIT_API_KEY") or "meetflow"
    secret = old.get("LIVEKIT_API_SECRET") or secrets.token_urlsafe(36)  # giữ khóa cũ nếu đã có

    update_env(
        root_env,
        {"LIVEKIT_NODE_IP": ip, "LIVEKIT_API_KEY": key, "LIVEKIT_API_SECRET": secret},
        header="# Docker Compose đọc file này. Do scripts/setup_lan.py tạo — KHÔNG commit.",
    )
    if backend_env.exists():
        update_env(backend_env, {"LIVEKIT_API_KEY": key, "LIVEKIT_API_SECRET": secret})
    else:
        print("! Chưa có backend/.env — hãy copy từ backend/.env.example rồi chạy lại script này.")

    created = make_cert(ip)

    print(f"IP của máy trong LAN : {ip}")
    print(f"Chứng chỉ HTTPS      : {'vừa tạo mới' if created else 'giữ chứng chỉ cũ (cùng IP)'} → {CERT_DIR}")
    print()
    print("Bước tiếp theo:")
    print("  1. docker compose up -d                      (bật / nạp lại LiveKit với IP mới)")
    print("  2. Khởi động lại Backend API")
    print("  3. cd frontend && npm run dev:lan            (web chạy https, máy khác trong LAN vào được)")
    print(f"  4. Mọi người mở  https://{ip}:5173  → lần đầu bấm 'Nâng cao' → 'Vẫn tiếp tục'")
    if ip == "127.0.0.1":
        print("\n! Không dò được IP LAN (máy chưa vào mạng?). Chỉ họp được trên chính máy này.")


if __name__ == "__main__":
    main()
