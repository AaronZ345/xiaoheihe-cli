"""只连接本次启动的本机 WebDriver，使用新的浏览器会话。"""

import asyncio
import socket
import tempfile
import time
from pathlib import Path

import httpx

from .errors import OperatorError


class NativeBrowser:
    def __init__(self, choice, *, headless=False):
        self.choice = choice
        self.headless = headless
        self.process = None
        self.client = None
        self.session_id = None
        self.profile_root = None

    async def __aenter__(self):
        if self.choice.engine == "safari" and self.headless:
            raise OperatorError("Safari 需要桌面窗口，不支持无头登录。", "browser")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = [str(self.choice.driver_path), "--port", str(port)]
        if self.choice.engine == "firefox":
            self.profile_root = tempfile.TemporaryDirectory(
                prefix="xiaoheihe-browser-",
                ignore_cleanup_errors=True,
                dir=Path.home()
                if str(self.choice.executable_path).startswith("/snap/firefox/")
                else None,
            )
            command.extend(("--host", "127.0.0.1", "--profile-root", self.profile_root.name))
        self.client = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=40, trust_env=False
        )
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process.returncode is not None:
                    raise OperatorError("浏览器驱动提前退出，请检查驱动版本。", "browser")
                try:
                    if (await self.client.get("/status")).status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise OperatorError("等待本机浏览器驱动启动超时。", "browser")
            capabilities = {
                "browserName": self.choice.engine,
                "pageLoadStrategy": "eager",
                "timeouts": {"pageLoad": 30000, "script": 10000},
            }
            if self.choice.engine == "firefox":
                capabilities["moz:firefoxOptions"] = {
                    "binary": str(self.choice.executable_path),
                    "args": ["-headless"] if self.headless else [],
                }
            result = await self.request(
                "POST", "/session", {"capabilities": {"alwaysMatch": capabilities}}
            )
            self.session_id = result.get("sessionId") if isinstance(result, dict) else None
            if not isinstance(self.session_id, str) or not self.session_id:
                raise OperatorError("浏览器驱动未创建有效会话。", "browser")
            return self
        except (OSError, httpx.HTTPError):
            await self.close()
            raise OperatorError("本机浏览器驱动无法启动或连接。", "browser") from None
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *args):
        await self.close()

    async def request(self, method, path, data=None):
        try:
            response = await self.client.request(method, path, json=data)
            result = response.json()
        except (httpx.HTTPError, ValueError):
            raise OperatorError("本机浏览器驱动请求失败。", "browser") from None
        value = result.get("value") if isinstance(result, dict) else None
        error = value.get("error") if isinstance(value, dict) else None
        if error or response.is_error:
            if error in ("no such window", "invalid session id"):
                raise OperatorError("登录窗口已关闭。", "login_cancelled", 3)
            message = (
                "Safari 需要启用开发菜单中的“允许远程自动化”，并完成 safaridriver 的首次授权。"
                if self.choice.engine == "safari" and path == "/session"
                else "浏览器驱动操作失败，请检查浏览器和驱动版本。"
            )
            raise OperatorError(message, "browser")
        if not isinstance(result, dict) or "value" not in result:
            raise OperatorError("本机浏览器驱动响应格式无效。", "browser")
        return value

    async def navigate(self, url):
        await self.request("POST", f"/session/{self.session_id}/url", {"url": url})

    async def click_login(self):
        await self.request(
            "POST",
            f"/session/{self.session_id}/execute/sync",
            {
                "script": "const b=[...document.querySelectorAll('button,[role=button]')].find(e=>e.textContent.trim()==='登录'); if(b) b.click();",
                "args": [],
            },
        )

    async def cookies(self):
        value = await self.request("GET", f"/session/{self.session_id}/cookie")
        if not isinstance(value, list) or any(
            not isinstance(item, dict)
            or not all(isinstance(item.get(key), str) for key in ("name", "value", "domain"))
            for item in value
        ):
            raise OperatorError("浏览器 Cookie 响应格式无效。", "browser")
        return value

    async def close(self):
        if self.client:
            try:
                if self.session_id:
                    await self.client.delete(f"/session/{self.session_id}", timeout=5)
            except httpx.HTTPError:
                pass
            finally:
                await self.client.aclose()
                self.client = None
                self.session_id = None
        if self.process:
            if self.process.returncode is None:
                try:
                    self.process.terminate()
                    await asyncio.wait_for(self.process.wait(), 5)
                except ProcessLookupError:
                    pass
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            self.process = None
        if self.profile_root:
            self.profile_root.cleanup()
            self.profile_root = None
