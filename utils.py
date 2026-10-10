"""
公共工具函数
"""

import os
import re


def extract_link_id(value: str) -> str:
    """从 URL 或纯文本中提取帖子 ID"""
    if value.startswith("http"):
        match = re.search(r"/link/(\d+)", value)
        if match:
            return match.group(1)
    return value.strip()


def get_daemon_socket_path() -> str:
    """获取守护进程 socket 路径"""
    return os.path.join(os.path.dirname(__file__), ".xiaoheihe-daemon.sock")


def get_daemon_pid_path() -> str:
    """获取守护进程 PID 文件路径"""
    from xhh_operator.session import private_home

    root = private_home()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return str(root / "daemon.pid")


def format_number(n: int) -> str:
    """格式化数字（如 484786 → 48.5w）"""
    if n >= 10000:
        return f"{n / 10000:.1f}w"
    elif n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def truncate_text(text: str, max_len: int = 50) -> str:
    """截断文本"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
