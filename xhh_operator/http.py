import asyncio
import time
from urllib.parse import urlsplit

import httpx

from .errors import AuthError, OperatorError, ProtocolError
from .signing import signed_params

API_BASE = "https://api.xiaoheihe.cn"
WEB_BASE = "https://www.xiaoheihe.cn"


class HeyboxAPI:
    """串行限速、失败即停；写请求永不自动重试。"""

    def __init__(self, cookies=(), *, transport=None, interval=0.6):
        jar = httpx.Cookies()
        for cookie in cookies:
            domain = cookie.get("domain", ".xiaoheihe.cn")
            if domain.lstrip(".") not in ("xiaoheihe.cn", "api.xiaoheihe.cn", "www.xiaoheihe.cn"):
                continue
            jar.set(cookie["name"], cookie["value"], domain=domain, path=cookie.get("path", "/"))
        self.client = httpx.AsyncClient(
            cookies=jar,
            transport=transport,
            timeout=25,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36",
                "Origin": WEB_BASE,
                "Referer": WEB_BASE + "/",
                "Accept": "application/json",
            },
        )
        self.interval = interval
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    def cookies(self):
        return [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
            }
            for c in self.client.cookies.jar
        ]

    async def request(
        self, path, *, params=None, form=None, signed=True, allow_status=(), extra=None
    ):
        parsed = urlsplit(path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or not path.startswith("/")
            or path.startswith("//")
        ):
            raise ValueError("仅接受小黑盒 API 的绝对路径。")
        query = {
            "os_type": "web",
            "app": "heybox",
            "client_type": "web",
            "version": "999.0.4",
            "web_version": "3.0",
            "x_app": "heybox_website",
            "x_client_type": "web",
            "x_os_type": "Mac",
            **(params or {}),
        }
        method = "POST" if form is not None else "GET"
        async with self._lock:
            await asyncio.sleep(max(0, self.interval - (time.monotonic() - self._last_request)))
            if signed:
                query.update(signed_params(path))
            if extra:
                query.update(extra(query))
            self._last_request = time.monotonic()
            try:
                response = await self.client.request(
                    method, API_BASE + path, params=query, data=form
                )
            except httpx.HTTPError:
                suffix = (
                    "写请求结果未知，请读取记录核实；不会自动重发。"
                    if form is not None
                    else "请稍后重试。"
                )
                raise OperatorError("连接小黑盒失败。" + suffix, "network", 6) from None
        if response.status_code in (401, 403):
            raise AuthError()
        if response.status_code == 429:
            raise OperatorError("小黑盒限流，已停止请求。", "rate_limit", 4)
        if not response.is_success:
            raise OperatorError(f"小黑盒返回 HTTP {response.status_code}，已停止请求。")
        try:
            data = response.json()
        except ValueError:
            raise ProtocolError() from None
        if not isinstance(data, dict):
            raise ProtocolError()
        status = data.get("status")
        if status in allow_status or status == "ok":
            return data
        if status in ("relogin", "not_login", "need_login", "login_required", "need_google_check"):
            raise AuthError("认证失败或需要二次验证，请执行 xiaoheihe login --browser。")
        if status in ("show_captcha", "need_captcha"):
            raise OperatorError(
                "小黑盒要求验证码，请通过 xiaoheihe login --browser 完成验证。", "captcha", 4
            )
        # Do not echo arbitrary upstream messages that may include session material.
        raise OperatorError("小黑盒拒绝了操作，请检查账号权限、内容及接口兼容性。")
