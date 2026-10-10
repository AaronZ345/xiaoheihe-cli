"""CLI 与兼容 SDK 共用的浏览器选择和启动逻辑。"""

import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from .errors import OperatorError

ENGINES = ("chromium", "firefox", "webkit")
CHANNELS = (
    "chrome",
    "chrome-beta",
    "chrome-dev",
    "chrome-canary",
    "msedge",
    "msedge-beta",
    "msedge-dev",
    "msedge-canary",
)
BROWSER_CHOICES = ("auto", *ENGINES, "edge", *CHANNELS)


@dataclass(frozen=True)
class BrowserChoice:
    engine: str
    channel: str | None = None
    executable_path: Path | None = None

    @property
    def name(self):
        return "custom-" + self.engine if self.executable_path else self.channel or self.engine


def choices(browser=None, *, channel=None, executable_path=None, environment=None):
    env = os.environ if environment is None else environment
    selected = browser or env.get("XHH_BROWSER_ENGINE", "auto")
    if selected not in BROWSER_CHOICES:
        raise OperatorError("不支持该浏览器，请查看 xiaoheihe browsers。", "input")
    if browser is None:
        channel = channel or env.get("XHH_BROWSER_CHANNEL") or None
        executable_path = executable_path or env.get("XHH_BROWSER_EXECUTABLE") or None
    if selected == "edge":
        selected = "msedge"
    if selected in CHANNELS:
        if channel and channel != selected:
            raise OperatorError("浏览器名称与 channel 参数冲突。", "input")
        channel, selected = selected, "chromium"
    if channel and channel not in (*CHANNELS, "chromium"):
        raise OperatorError("不支持该 channel，请选择 Chromium、Chrome 或 Edge 通道。", "input")
    if channel and selected not in ("auto", "chromium"):
        raise OperatorError("Firefox 和 WebKit 不接受 Chromium channel 参数。", "input")
    if channel and executable_path:
        raise OperatorError("channel 和 executable-path 不能同时指定。", "input")
    if executable_path:
        path = Path(executable_path).expanduser()
        if not path.is_file():
            raise OperatorError("指定的浏览器可执行文件不存在。", "browser")
        return [BrowserChoice("chromium" if selected == "auto" else selected, executable_path=path)]
    if channel:
        return [BrowserChoice("chromium", channel=channel)]
    if selected != "auto":
        return [BrowserChoice(selected)]
    return [
        BrowserChoice("chromium"),
        BrowserChoice("chromium", "chrome"),
        BrowserChoice("chromium", "msedge"),
        BrowserChoice("firefox"),
        BrowserChoice("webkit"),
    ]


def system_browser(channel):
    """检查标准安装位置，不读取任何浏览器的用户配置或会话。"""
    family = "chrome" if channel.startswith("chrome") else "msedge"
    if sys.platform == "darwin":
        names = {
            "chrome": "Google Chrome",
            "chrome-beta": "Google Chrome Beta",
            "chrome-dev": "Google Chrome Dev",
            "chrome-canary": "Google Chrome Canary",
            "msedge": "Microsoft Edge",
            "msedge-beta": "Microsoft Edge Beta",
            "msedge-dev": "Microsoft Edge Dev",
            "msedge-canary": "Microsoft Edge Canary",
        }
        name = names[channel]
        return Path("/Applications") / f"{name}.app/Contents/MacOS/{name}"
    if sys.platform == "win32":
        relative = (
            "Google/Chrome/Application/chrome.exe"
            if family == "chrome"
            else "Microsoft/Edge/Application/msedge.exe"
        )
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if root := os.environ.get(variable):
                path = Path(root) / relative
                if path.is_file():
                    return path
        return None
    for command in (
        ("google-chrome", "google-chrome-stable")
        if family == "chrome"
        else ("microsoft-edge", "microsoft-edge-stable")
    ):
        if path := shutil.which(command):
            return Path(path)
    return None


def inventory(playwright):
    result = []
    for engine in ENGINES:
        result.append(
            {
                "browser": engine,
                "available": Path(getattr(playwright, engine).executable_path).is_file(),
                "install": f"playwright install {engine}",
            }
        )
    for channel in ("chrome", "msedge"):
        path = system_browser(channel)
        result.append(
            {
                "browser": channel,
                "available": bool(path and path.is_file()),
                "install": "安装对应浏览器，或使用 Chromium",
            }
        )
    return result


async def launch_browser(
    playwright,
    *,
    browser=None,
    channel=None,
    executable_path=None,
    headless=False,
    environment=None,
):
    env = os.environ if environment is None else environment
    if (
        not headless
        and sys.platform.startswith("linux")
        and not any(env.get(key) for key in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"))
    ):
        raise OperatorError(
            "当前环境没有图形显示服务，请使用扫码登录或在桌面环境执行网页登录。", "browser"
        )
    candidates = choices(browser, channel=channel, executable_path=executable_path, environment=env)
    for choice in candidates:
        options = {"headless": headless}
        if choice.channel:
            options["channel"] = choice.channel
        if choice.executable_path:
            options["executable_path"] = str(choice.executable_path)
        if choice.engine == "chromium":
            arguments = shlex.split(env.get("XHH_BROWSER_ARGS", ""))
            if sys.platform.startswith("linux"):
                arguments.append("--disable-dev-shm-usage")
                if (hasattr(os, "geteuid") and os.geteuid() == 0) or env.get(
                    "XHH_BROWSER_NO_SANDBOX", ""
                ).lower() in ("1", "true", "yes", "on"):
                    arguments.extend(("--no-sandbox", "--disable-setuid-sandbox"))
            if arguments:
                options["args"] = list(dict.fromkeys(arguments))
        try:
            instance = await getattr(playwright, choice.engine).launch(**options)
            return instance, choice.name
        except PlaywrightError:
            if len(candidates) == 1:
                instruction = (
                    "检查可执行文件及其版本是否兼容 Playwright。"
                    if choice.executable_path
                    else (
                        "检查对应 Chrome/Edge 通道是否已安装。"
                        if choice.channel
                        else f"请执行 playwright install {choice.engine}。"
                    )
                )
                raise OperatorError(f"无法启动 {choice.name}。{instruction}", "browser") from None
    raise OperatorError(
        "没有可用的浏览器，请执行 playwright install chromium，或通过 --browser 选择已安装的浏览器。",
        "browser",
    )
