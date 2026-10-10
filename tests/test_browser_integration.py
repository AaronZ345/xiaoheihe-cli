"""真实浏览器对合成登录页面的测试，不访问远端网站或本机账号。"""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from xhh_operator import auth
from xhh_operator.browsers import choices, launch_browser, system_browser
from xhh_operator.http import HeyboxAPI
from xhh_operator.session import SessionStore

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("XHH_RUN_BROWSER_TESTS") != "1",
        reason="set XHH_RUN_BROWSER_TESTS=1 for local browser tests",
    ),
]


def cached_binary(expected, engine):
    path = Path(expected)
    if path.is_file():
        return path
    for parent in path.parents:
        if parent.name.startswith(engine + "-") and parent.name.rsplit("-", 1)[-1].isdigit():
            relative = path.relative_to(parent)
            candidates = sorted(
                parent.parent.glob(engine + "-*"), key=lambda p: p.name, reverse=True
            )
            for candidate in candidates:
                if (binary := candidate / relative).is_file():
                    return binary
    pytest.skip("browser runtime not installed")


@pytest.mark.parametrize("browser_name", ["chromium", "firefox", "webkit", "chrome", "msedge"])
def test_real_engine_completes_isolated_login_with_fixture_data(
    browser_name, tmp_path, monkeypatch
):
    choice = choices(browser_name, environment={})[0]
    engine = choice.engine
    observed = []
    original_launch = launch_browser
    html = """<meta charset="utf-8"><button onclick="document.cookie='user_heybox_id=42; path=/';document.cookie='user_pkey=fixture-only; path=/'">登录</button>"""

    async def route(request):
        await request.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    async def fixture_launch(playwright, **kwargs):
        if choice.channel:
            path = system_browser(choice.channel)
            if not path or not path.is_file():
                pytest.skip("named system browser not installed")
            browser, name = await original_launch(
                playwright, browser=browser_name, headless=True, environment={}
            )
        else:
            executable = cached_binary(getattr(playwright, engine).executable_path, engine)
            browser, name = await original_launch(
                playwright,
                browser=engine,
                executable_path=executable,
                headless=True,
                environment={},
            )
        create_context = browser.new_context

        async def new_context():
            context = await create_context()
            await context.route("**/*", route)
            return context

        monkeypatch.setattr(browser, "new_context", new_context)
        return browser, name

    def verify_request(request):
        observed.append(request)
        assert request.url.path == "/account/restore_login"
        assert "fixture-only" in request.headers.get("cookie", "")
        return httpx.Response(
            200, json={"status": "ok", "result": {"profile": {"heybox_id": "42"}}}
        )

    monkeypatch.setattr(auth, "launch_browser", fixture_launch)
    monkeypatch.setattr(
        auth,
        "HeyboxAPI",
        lambda cookies: HeyboxAPI(
            cookies, transport=httpx.MockTransport(verify_request), interval=0
        ),
    )
    store = SessionStore(tmp_path / "session")
    result = asyncio.run(auth.login_browser(store, timeout=5, browser_name=browser_name))
    assert result["authenticated"] and result["user_id"] == "42"
    assert result["browser"] == (choice.channel or "custom-" + engine)
    assert store.load()["user_id"] == "42" and len(observed) == 1
