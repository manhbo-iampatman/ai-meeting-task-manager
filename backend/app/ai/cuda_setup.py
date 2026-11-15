"""Giúp Windows tìm thấy thư viện CUDA (cuBLAS, cuDNN) cài qua pip.

Gói pip `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` đặt file .dll trong
site-packages/nvidia/<tên>/bin — Windows không tự tìm ở đó, nên phải thêm
thư mục này vào PATH trước khi faster-whisper chạy trên GPU.
Nhờ vậy KHÔNG cần cài CUDA Toolkit (vài GB) vào máy.
"""

import os
import sys
from pathlib import Path

_done = False


def setup_cuda_dlls() -> list[str]:
    global _done
    if _done or sys.platform != "win32":
        return []
    added: list[str] = []
    for site in map(Path, sys.path):
        nvidia_dir = site / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        for bin_dir in nvidia_dir.glob("*/bin"):
            p = str(bin_dir)
            os.add_dll_directory(p)
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
            added.append(p)
    _done = True
    return added
