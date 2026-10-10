import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from xhh_operator import auth, browsers, webdriver
from xhh_operator.browsers import BrowserChoice, choices, launch_browser, system_browser
from xhh_operator.errors import OperatorError
from xhh_operator.session import SessionStore


@pytest.mark.parametrize("name", browsers.WINDOWS_PATHS)
@pytest.mark.parametrize("location", ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"])
def test_windows_detects_browser_in_each_install_scope(name, location, tmp_path, monkeypatch):
    path = tmp_path / browsers.WINDOWS_PATHS[name][0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    monkeypatch.setattr(browsers.shutil, "which", lambda _: None)
    assert system_browser(name, platform="win32", environment={location: str(tmp_path)}) == path


@pytest.mark.parametrize("name", browsers.MAC_APPS)
def test_macos_detects_user_application_installation(name, tmp_path, monkeypatch):
    app, binary = browsers.MAC_APPS[name]
    path = tmp_path / f"Applications/{app}.app/Contents/MacOS/{binary}"
    path.parent.mkdir(parents=True)
    path.touch()
    monkeypatch.setattr(browsers.Path, "is_file", lambda candidate: candidate == path)
    assert system_browser(name, platform="darwin", home=tmp_path) == path


@pytest.mark.parametrize("name", browsers.LINUX_COMMANDS)
def test_linux_detects_exact_requested_browser_without_family_substitution(
    name, tmp_path, monkeypatch
):
    path = tmp_path / browsers.LINUX_COMMANDS[name][-1]
    path.touch()
    seen = []

    def which(command):
        seen.append(command)
        return str(path) if command == path.name else None

    monkeypatch.setattr(browsers.shutil, "which", which)
    assert system_browser(name, platform="linux", environment={}) == path
    assert set(seen).issubset(browsers.LINUX_COMMANDS[name])


@pytest.mark.parametrize("name", browsers.NAMED_BROWSERS)
def test_named_chromium_uses_its_binary_and_fresh_context(name, tmp_path, monkeypatch):
    path = tmp_path / "browser"
    path.touch()
    monkeypatch.setattr(
        browsers, "system_browser", lambda requested: path if requested == name else None
    )
    seen = []

    class Engine:
        async def launch(self, **kwargs):
            seen.append(kwargs)
            return "fixture-instance"

    instance, selected = asyncio.run(
        launch_browser(
            SimpleNamespace(chromium=Engine()), browser=name, headless=True, environment={}
        )
    )
    assert instance == "fixture-instance" and selected == name
    assert seen[0]["executable_path"] == str(path)
    assert "user_data_dir" not in seen[0]


def test_missing_named_browser_fails_without_selecting_another_browser(monkeypatch):
    monkeypatch.setattr(browsers, "system_browser", lambda _: None)
    with pytest.raises(OperatorError, match="brave"):
        choices("brave", environment={})


def test_native_driver_requires_matching_platform_and_explicit_driver(tmp_path, monkeypatch):
    executable, driver = tmp_path / "firefox", tmp_path / "driver"
    executable.touch()
    driver.touch()
    choice = choices(
        "firefox-system", executable_path=executable, driver_path=driver, environment={}
    )[0]
    assert choice.backend == "webdriver" and choice.engine == "firefox"
    monkeypatch.setattr(browsers.sys, "platform", "linux")
    with pytest.raises(OperatorError, match="macOS"):
        choices("safari", environment={})


class Process:
    returncode = None

    def terminate(self):
        self.returncode = 0

    async def wait(self):
        return self.returncode


def native_runtime(monkeypatch, handler):
    real_client = httpx.AsyncClient
    process = Process()
    commands = []

    async def create(*arguments, **kwargs):
        commands.append(arguments)
        assert kwargs["stdout"] == asyncio.subprocess.DEVNULL
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
        return process

    monkeypatch.setattr(webdriver.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(
        webdriver.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return process, commands


@pytest.mark.parametrize("engine", ["firefox", "safari"])
def test_native_session_cookie_reads_and_cleanup_use_owned_local_driver(
    engine, tmp_path, monkeypatch
):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.host == "127.0.0.1"
        assert not request.headers.get("cookie")
        value = None
        if request.url.path == "/status":
            value = {"ready": True}
        elif request.url.path == "/session":
            value = {"sessionId": "fixture"}
        elif request.url.path.endswith("/cookie"):
            value = [{"name": "pkey", "value": "fixture-only", "domain": ".xiaoheihe.cn"}]
        return httpx.Response(200, json={"value": value})

    process, commands = native_runtime(monkeypatch, handler)
    choice = BrowserChoice(
        engine,
        executable_path=tmp_path / "browser",
        product=engine,
        backend="webdriver",
        driver_path=tmp_path / "driver",
    )

    async def check():
        async with webdriver.NativeBrowser(choice) as browser:
            await browser.navigate("http://127.0.0.1/fixture")
            await browser.click_login()
            assert (await browser.cookies())[0]["value"] == "fixture-only"
        assert browser.client is None and browser.profile_root is None

    asyncio.run(check())
    payload = json.loads(
        next(request.content for request in seen if request.url.path == "/session")
    )
    capabilities = payload["capabilities"]["alwaysMatch"]
    assert capabilities["browserName"] == engine
    assert "profile" not in capabilities.get("moz:firefoxOptions", {})
    assert commands[0][0] == str(choice.driver_path)
    assert "--enable" not in commands[0]
    assert process.returncode == 0
    assert sum(request.method == "DELETE" for request in seen) == 1


def test_native_session_failure_is_redacted_and_does_not_retry_creation(tmp_path, monkeypatch):
    sessions = []

    def handler(request):
        if request.url.path == "/status":
            return httpx.Response(200, json={"value": {"ready": True}})
        sessions.append(request)
        return httpx.Response(
            500, json={"value": {"error": "session not created", "message": "fixture-private"}}
        )

    process, _ = native_runtime(monkeypatch, handler)
    choice = BrowserChoice("safari", driver_path=tmp_path / "driver", backend="webdriver")

    async def check():
        with pytest.raises(OperatorError, match="远程自动化") as error:
            async with webdriver.NativeBrowser(choice):
                pass
        assert "fixture-private" not in str(error.value)

    asyncio.run(check())
    assert len(sessions) == 1 and process.returncode == 0


def test_foreign_site_login_cookies_never_trigger_account_verification(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("foreign cookies must not verify an account")

    monkeypatch.setattr(auth, "HeyboxAPI", forbidden)
    cookies = [
        {"name": name, "value": "fixture-only", "domain": "example.test"}
        for name in ("pkey", "heybox_id")
    ]
    assert (
        asyncio.run(
            auth.finish_browser_login(SessionStore(tmp_path / "session"), cookies, "safari")
        )
        is None
    )


def test_windows_default_session_uses_local_app_data(tmp_path, monkeypatch):
    from xhh_operator import session

    monkeypatch.delenv("XHH_OPERATOR_HOME", raising=False)
    monkeypatch.setattr(session.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert session.private_home() == tmp_path / "xiaoheihe-cli"
