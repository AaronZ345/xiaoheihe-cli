"""仅在当前工具的私有目录保存会话；不读取其他浏览器或工具的凭据。"""

import json
import os
import sys
import tempfile
from pathlib import Path

from .errors import AuthError, OperatorError

SECRET_NAMES = {"pkey", "user_pkey", "x_xhh_tokenid", "token", "password", "cookie", "cookies"}


def private_home() -> Path:
    if root := os.environ.get("XHH_OPERATOR_HOME"):
        return Path(root).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/xiaoheihe-cli"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "xiaoheihe-cli"


def safe_result(value):
    """过滤账号接口可能回传的会话字段，所有 JSON 输出均经过此函数。"""
    if isinstance(value, dict):
        return {
            k: safe_result(v)
            for k, v in value.items()
            if k.lower() not in SECRET_NAMES
            and not any(word in k.lower() for word in ("token", "secret", "password", "pkey"))
        }
    if isinstance(value, list):
        return [safe_result(v) for v in value]
    return value


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.root = root or private_home()
        self.path = self.root / "session.json"

    def _prepare(self):
        if self.root.is_symlink() or self.path.is_symlink():
            raise OperatorError("会话目录或文件不能是符号链接。", "local")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def load(self) -> dict | None:
        if self.root.is_symlink() or self.path.is_symlink():
            raise OperatorError("会话文件不能是符号链接。", "local")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, OSError):
            raise OperatorError("无法读取本地会话，请重新登录。", "local") from None
        if not isinstance(data, dict) or not isinstance(data.get("cookies"), list):
            raise OperatorError("本地会话格式无效，请重新登录。", "local")
        for cookie in data["cookies"]:
            if not isinstance(cookie, dict) or not all(
                isinstance(cookie.get(k), str) for k in ("name", "value")
            ):
                raise OperatorError("本地会话格式无效，请重新登录。", "local")
        if not isinstance(data.get("user_id"), str) or not data["user_id"]:
            raise OperatorError("本地会话缺少账号身份，请重新登录。", "local")
        return data

    def require(self) -> dict:
        data = self.load()
        if not data:
            raise AuthError("尚未登录，请先执行 xiaoheihe login。")
        return data

    def save(self, cookies: list[dict], user_id: str):
        if not user_id or not cookies:
            raise AuthError("没有有效的账号身份，会话未保存。")
        self._prepare()
        filtered = [
            c
            for c in cookies
            if c.get("domain", "").lstrip(".")
            in ("xiaoheihe.cn", "api.xiaoheihe.cn", "www.xiaoheihe.cn")
        ]
        if not filtered:
            raise AuthError("没有小黑盒会话，会话未保存。")
        fd, filename = tempfile.mkstemp(prefix=".session-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump({"user_id": user_id, "cookies": filtered}, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(filename, self.path)
        finally:
            Path(filename).unlink(missing_ok=True)

    def delete(self):
        if self.path.is_symlink():
            raise OperatorError("会话文件不能是符号链接。", "local")
        self.path.unlink(missing_ok=True)
