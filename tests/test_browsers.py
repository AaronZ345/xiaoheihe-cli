import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

from xhh_operator.browsers import BrowserChoice, choices, launch_browser
from xhh_operator.cli import parser
from xhh_operator.errors import OperatorError


@pytest.mark.parametrize(
    "name,engine,channel",
    [
        ("chromium", "chromium", None),
        ("chrome", "chromium", "chrome"),
        ("edge", "chromium", "msedge"),
        ("msedge", "chromium", "msedge"),
        ("chrome-beta", "chromium", "chrome-beta"),
        ("firefox", "firefox", None),
        ("webkit", "webkit", None),
    ],
)
def test_browser_selection_preserves_requested_engine(name, engine, channel):
    assert choices(name, environment={}) == [BrowserChoice(engine, channel)]


def test_explicit_browser_overrides_unrelated_environment():
    assert choices(
        "firefox",
        environment={"XHH_BROWSER_CHANNEL": "chrome", "XHH_BROWSER_EXECUTABLE": "/nonexistent"},
    ) == [BrowserChoice("firefox")]


def test_custom_binary_requires_a_real_file(tmp_path):
    path = tmp_path / "browser"
    path.write_text("fixture")
    assert choices("chromium", executable_path=path, environment={}) == [
        BrowserChoice("chromium", executable_path=path)
    ]
    with pytest.raises(OperatorError, match="不存在"):
        choices("chromium", executable_path=tmp_path / "missing", environment={})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"browser": "firefox", "channel": "chrome"},
        {"browser": "webkit", "channel": "msedge"},
        {"browser": "safari", "channel": "chrome"},
        {"browser": "chrome", "channel": "msedge"},
    ],
)
def test_invalid_combinations_fail_before_launch(kwargs):
    with pytest.raises(OperatorError):
        choices(**kwargs, environment={})


def test_named_browser_failure_does_not_switch_to_another_browser():
    calls = []

    class Engine:
        async def launch(self, **kwargs):
            calls.append(kwargs)
            raise PlaywrightError("private runtime details")

    fake = SimpleNamespace(chromium=Engine(), firefox=Engine(), webkit=Engine())
    with pytest.raises(OperatorError, match="install firefox") as error:
        asyncio.run(launch_browser(fake, browser="firefox", headless=True, environment={}))
    assert len(calls) == 1
    assert "private runtime" not in str(error.value)


def test_auto_can_recover_from_missing_chromium_with_installed_chrome():
    calls = []
    instance = object()

    class Engine:
        async def launch(self, **kwargs):
            calls.append(kwargs)
            if not kwargs.get("channel"):
                raise PlaywrightError("not installed")
            return instance

    fake = SimpleNamespace(chromium=Engine())
    result, name = asyncio.run(launch_browser(fake, browser="auto", headless=True, environment={}))
    assert result is instance and name == "chrome"
    assert calls[0].get("channel") is None and calls[1]["channel"] == "chrome"


def test_login_cli_keeps_old_flag_and_accepts_browser_names():
    assert parser().parse_args(["login", "--browser"]).browser == "auto"
    assert parser().parse_args(["login", "--browser", "chromium"]).browser == "chromium"
    args = parser().parse_args(["login", "--browser", "firefox", "--executable-path", "browser"])
    assert args.executable_path == Path("browser")


def test_legacy_sdk_stops_driver_after_browser_launch_failure(monkeypatch):
    from browser_manager import BrowserManager

    class Driver:
        stopped = False

        async def stop(self):
            self.stopped = True

    driver = Driver()
    manager = BrowserManager(headless=True)
    manager._playwright = driver

    async def unavailable(*args, **kwargs):
        raise OperatorError("runtime unavailable", "browser")

    monkeypatch.setattr("xhh_operator.browsers.launch_browser", unavailable)
    with pytest.raises(OperatorError):
        asyncio.run(manager._launch_browser())
    assert driver.stopped and manager._playwright is None
