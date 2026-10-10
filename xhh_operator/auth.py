import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import qrcode

from .browsers import launch_browser
from .errors import AuthError, OperatorError, ProtocolError
from .http import WEB_BASE, HeyboxAPI
from .session import SessionStore


def identity(data: dict) -> str:
    result = data.get("result") or {}
    if not isinstance(result, dict):
        raise ProtocolError("账号身份响应格式已变化。")
    profile = result.get("profile")
    detail = result.get("account_detail")
    if (profile is not None and not isinstance(profile, dict)) or (
        detail is not None and not isinstance(detail, dict)
    ):
        raise ProtocolError("账号身份响应格式已变化。")
    for value in (
        (profile or {}).get("heybox_id"),
        (detail or {}).get("userid"),
        result.get("heybox_id"),
    ):
        if value is None or value == 0 or value == "0":
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ProtocolError("账号身份标识格式已变化。")
        if str(value).strip():
            return str(value).strip()
    raise AuthError("认证未返回有效账号身份，会话未保存。")


async def verify(api: HeyboxAPI, expected_user: str | None = None) -> str:
    user_id = identity(await api.request("/account/restore_login"))
    if expected_user and user_id != expected_user:
        raise AuthError("当前账号与保存的账号不一致，请重新登录。")
    return user_id


def normalize_cookies(cookies: list[dict], result: dict | None = None) -> list[dict]:
    result = result or {}
    cookies = [
        cookie
        for cookie in cookies
        if cookie.get("domain", "").lstrip(".")
        in ("xiaoheihe.cn", "api.xiaoheihe.cn", "www.xiaoheihe.cn")
    ]
    names = {cookie["name"]: cookie["value"] for cookie in cookies}
    user = str(
        result.get("heybox_id") or names.get("user_heybox_id") or names.get("heybox_id") or ""
    )
    pkey = result.get("pkey") or names.get("user_pkey") or names.get("pkey")
    aliases = {"user_heybox_id": user, "heybox_id": user, "user_pkey": pkey, "pkey": pkey}
    preserved = [cookie for cookie in cookies if cookie["name"] not in aliases]
    return preserved + [
        {"name": name, "value": str(value), "domain": ".xiaoheihe.cn", "path": "/", "secure": True}
        for name, value in aliases.items()
        if value
    ]


async def login_qr(store: SessionStore, *, timeout=180, qr_file: Path | None = None, on_ready=None):
    store._prepare()
    try:
        if qr_file is None:
            fd, filename = tempfile.mkstemp(prefix="login-qr-", suffix=".png", dir=store.root)
            qr_path = Path(filename)
        else:
            qr_path = Path(qr_file)
            fd = os.open(
                qr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
    except FileExistsError:
        raise OperatorError("二维码输出文件已存在，请选择新的临时路径。", "local") from None
    except OSError:
        raise OperatorError("无法创建临时二维码文件，请检查输出目录。", "local") from None
    try:
        with os.fdopen(fd, "wb") as file:
            async with HeyboxAPI() as api:
                response = await api.request("/account/get_qrcode_url/", params={"app": "web"})
                result = response.get("result") or {}
                if not isinstance(result, dict):
                    raise ProtocolError("二维码响应格式已变化。")
                url = result.get("qr_url", "")
                token = parse_qs(urlsplit(url).query).get("qr", [""])[0]
                if not token:
                    raise ProtocolError("二维码响应缺少登录标识。")
                qr = qrcode.QRCode(border=2)
                qr.add_data(url)
                qr.make(fit=True)
                qr.make_image().save(file)
                file.flush()
                if on_ready:
                    await on_ready(qr_path)
                print(
                    f"请用小黑盒 App 扫码并确认。二维码图片：{qr_path}", file=sys.stderr, flush=True
                )
                if sys.stderr.isatty():
                    qr.print_ascii(out=sys.stderr, invert=True)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    await asyncio.sleep(2)
                    response = await api.request(
                        "/account/qr_state/", params={"app": "web", "qr": token}
                    )
                    result = response.get("result") or {}
                    if not isinstance(result, dict):
                        raise ProtocolError("二维码登录状态格式已变化。")
                    state = result.get("error")
                    if state in ("wait", "ready"):
                        continue
                    if state == "ok":
                        user_id = identity(response)
                        cookies = normalize_cookies(api.cookies(), {**result, "heybox_id": user_id})
                        async with HeyboxAPI(cookies) as authenticated:
                            await verify(authenticated, user_id)
                        store.save(cookies, user_id)
                        return {"authenticated": True, "user_id": user_id, "method": "qr"}
                    raise OperatorError(
                        "二维码已失效，请重新执行 xiaoheihe login。", "qr_expired", 3
                    )
                raise OperatorError("等待扫码超时，会话未保存。", "login_timeout", 3)
    finally:
        qr_path.unlink(missing_ok=True)


async def login_browser(
    store: SessionStore, *, timeout=300, browser_name=None, channel=None, executable_path=None
):
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    print("正在打开小黑盒官方登录页，请在浏览器中完成登录和验证。", file=sys.stderr, flush=True)
    async with async_playwright() as playwright:
        browser, selected = await launch_browser(
            playwright, browser=browser_name, channel=channel, executable_path=executable_path
        )
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(WEB_BASE, wait_until="domcontentloaded", timeout=30000)
            button = page.get_by_role("button", name="登录", exact=True)
            if await button.count():
                await button.click()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if page.is_closed():
                    raise OperatorError("登录窗口已关闭，会话未保存。", "login_cancelled", 3)
                cookies = await context.cookies()
                names = {c["name"]: c["value"] for c in cookies}
                if (names.get("user_pkey") or names.get("pkey")) and (
                    names.get("user_heybox_id") or names.get("heybox_id")
                ):
                    cookies = normalize_cookies(cookies)
                    async with HeyboxAPI(cookies) as api:
                        user_id = await verify(api)
                    store.save(cookies, user_id)
                    return {
                        "authenticated": True,
                        "user_id": user_id,
                        "method": "browser",
                        "browser": selected,
                    }
                await asyncio.sleep(2)
            raise OperatorError("等待网页登录超时，会话未保存。", "login_timeout", 3)
        except PlaywrightError:
            raise OperatorError("浏览器登录操作失败或窗口已关闭，会话未保存。", "browser") from None
        finally:
            await browser.close()


async def import_cookies(store: SessionStore, path: Path):
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise OperatorError("无法读取 Cookie 文件。", "local") from None
    cookies = []
    for pair in text.split(";"):
        name, separator, value = pair.strip().partition("=")
        if separator and name and value:
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".xiaoheihe.cn",
                    "path": "/",
                    "secure": True,
                }
            )
    if not cookies:
        raise OperatorError("Cookie 文件格式无效。", "local")
    cookies = normalize_cookies(cookies)
    async with HeyboxAPI(cookies) as api:
        user_id = await verify(api)
    store.save(cookies, user_id)
    return {"authenticated": True, "user_id": user_id, "method": "import"}
