import asyncio
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from xhh_operator import auth
from xhh_operator.browsers import browser_driver, system_browser
from xhh_operator.http import HeyboxAPI
from xhh_operator.session import SessionStore
from xhh_operator.webdriver import NativeBrowser

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("XHH_RUN_NATIVE_TESTS") != "1",
        reason="set XHH_RUN_NATIVE_TESTS=1 for native browser tests",
    ),
]


@pytest.mark.parametrize("name", ["firefox-system", "safari"])
def test_native_browser_completes_login_on_local_fixture(name, tmp_path, monkeypatch):
    executable, driver = system_browser(name), browser_driver(name)
    if name == "safari" and sys.platform != "darwin":
        pytest.skip("Safari requires macOS")
    if not executable or not driver:
        if os.environ.get("XHH_REQUIRE_NATIVE_TESTS") == "1":
            pytest.fail("required native browser or driver not installed")
        pytest.skip("native browser or driver not installed")
    body = """<meta charset='utf-8'><button onclick="document.cookie='pkey=fixture-only; path=/';document.cookie='heybox_id=42; path=/'">登录</button>""".encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(auth, "WEB_BASE", f"http://127.0.0.1:{server.server_port}")
    normalize = auth.normalize_cookies

    def fixture_cookies(cookies, result=None):
        assert all(item["domain"].lstrip(".") == "127.0.0.1" for item in cookies)
        return normalize([{**item, "domain": ".xiaoheihe.cn"} for item in cookies], result)

    monkeypatch.setattr(auth, "normalize_cookies", fixture_cookies)
    monkeypatch.setenv("DISPLAY", os.environ.get("DISPLAY", ":fixture"))
    monkeypatch.setattr(
        "xhh_operator.webdriver.NativeBrowser",
        lambda choice: NativeBrowser(choice, headless=name != "safari"),
    )

    def handler(request):
        assert request.url.path == "/account/restore_login"
        assert "fixture-only" in request.headers.get("cookie", "")
        return httpx.Response(
            200, json={"status": "ok", "result": {"profile": {"heybox_id": "42"}}}
        )

    monkeypatch.setattr(
        auth,
        "HeyboxAPI",
        lambda cookies: HeyboxAPI(cookies, transport=httpx.MockTransport(handler), interval=0),
    )
    store = SessionStore(tmp_path / "session")
    try:
        result = asyncio.run(auth.login_browser(store, browser_name=name, timeout=10))
        assert result["authenticated"] and result["browser"] == name
        assert store.load()["user_id"] == "42"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
