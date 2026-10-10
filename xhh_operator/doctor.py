"""本地诊断默认只看运行时和文件元信息，不读取会话内容。"""

import importlib.util
import os
import shutil
import stat
import sys

from playwright.async_api import async_playwright

from .auth import verify
from .browsers import inventory
from .errors import OperatorError
from .http import HeyboxAPI
from .session import SessionStore


async def diagnose(*, verify_login=False, store=None):
    store = store or SessionStore()
    session = {"present": False, "regular_file": None, "private_permissions": None}
    try:
        if store.root.is_symlink() or store.path.is_symlink():
            session.update({"present": True, "regular_file": False, "unsafe_symlink": True})
        elif store.path.exists():
            metadata = store.path.stat()
            session.update({"present": True, "regular_file": stat.S_ISREG(metadata.st_mode)})
            if os.name != "nt":
                session["private_permissions"] = (
                    stat.S_IMODE(metadata.st_mode) == 0o600
                    and stat.S_IMODE(store.root.stat().st_mode) == 0o700
                )
    except OSError:
        session["error"] = "metadata_unavailable"
    async with async_playwright() as playwright:
        browsers = inventory(playwright)
    result = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "mcp_available": importlib.util.find_spec("mcp") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "browsers": browsers,
        "session": session,
        "checked_login": False,
    }
    if verify_login:
        result["checked_login"] = True
        try:
            data = store.require()
            async with HeyboxAPI(data["cookies"]) as api:
                await verify(api, data["user_id"])
            result["authenticated"] = True
        except OperatorError as error:
            result.update({"authenticated": False, "login_error": error.code})
    return result
