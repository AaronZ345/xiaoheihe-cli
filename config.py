"""
小黑盒 CLI 集中配置管理

Cookie 加载优先级:
    1. --cookie 命令行参数（最高）
    2. XHH_COOKIE 环境变量
    3. 本工具私有目录内的 session.json（自动持久化）

用法:
    from config import get_cookie, save_cookie, Config
    cookie = get_cookie()          # 自动从所有来源加载
    save_cookie("key=val; ...")   # 持久化到私有会话文件
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from xhh_operator.session import SessionStore, private_home

logger = logging.getLogger(__name__)

# ---- 常量 ----
_COOKIE_ENV_KEY = "XHH_COOKIE"

_COOKIE_FILE = private_home() / "session.json"
_DEFAULT_TIMEOUT = 30  # 秒
_DEFAULT_RETRY = 2


@dataclass
class Config:
    """全局配置"""

    # Cookie
    cookie: str = ""
    cookie_file: Path = field(default_factory=lambda: _COOKIE_FILE)

    # 浏览器
    headless: bool = True

    # 网络
    timeout: int = _DEFAULT_TIMEOUT
    max_retry: int = _DEFAULT_RETRY

    # 守护进程
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 19810
    daemon_pid_file: Optional[Path] = None

    # 输出
    output_format: str = "json"  # json | table | csv
    output_file: Optional[str] = None

    def __post_init__(self):
        if self.daemon_pid_file is None:
            # 延迟导入避免循环依赖
            try:
                from utils import get_daemon_pid_path

                self.daemon_pid_file = Path(get_daemon_pid_path())
            except ImportError:
                self.daemon_pid_file = Path(os.getcwd()) / ".xhh_daemon.pid"


def get_cookie(override: Optional[str] = None) -> str:
    """
    获取 Cookie（按优先级）。

    Args:
        override: 命令行传入的 Cookie 字符串，最高优先级

    Returns:
        Cookie 字符串，空字符串表示未找到
    """
    # 1. 显式传入
    if override and override.strip():
        return override.strip()

    # 2. 环境变量
    env_val = os.environ.get(_COOKIE_ENV_KEY, "")
    if env_val.strip():
        return env_val.strip()

    session = SessionStore().load()
    if session:
        return "; ".join(f"{c['name']}={c['value']}" for c in session["cookies"])
    return ""


def save_cookie(cookie_string: str) -> Path:
    """
    持久化 Cookie 到本工具的私有会话文件。

    Args:
        cookie_string: 完整的 Cookie 字符串

    Returns:
        写入的私有会话文件路径
    """
    from browser_manager import BrowserManager

    cookies = BrowserManager._parse_cookie_string(cookie_string)
    user = BrowserManager._extract_heybox_id(cookies)
    SessionStore().save(cookies, user or "")
    return SessionStore().path


def clear_cookie() -> bool:
    """清除持久化的 Cookie。返回是否成功删除。"""
    SessionStore().delete()
    return True


def has_stored_cookie() -> bool:
    """检查是否有已存储的 Cookie。"""
    return bool(get_cookie())
