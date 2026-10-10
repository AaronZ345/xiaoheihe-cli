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
NAMED_BROWSERS = ("chromium-system", "brave", "vivaldi", "opera", "arc")
NATIVE_BROWSERS = ("firefox-system", "safari")
BROWSER_CHOICES = ("auto", *ENGINES, "edge", *CHANNELS, *NAMED_BROWSERS, *NATIVE_BROWSERS)

MAC_APPS = {
    "chrome": ("Google Chrome", "Google Chrome"),
    "chrome-beta": ("Google Chrome Beta", "Google Chrome Beta"),
    "chrome-dev": ("Google Chrome Dev", "Google Chrome Dev"),
    "chrome-canary": ("Google Chrome Canary", "Google Chrome Canary"),
    "msedge": ("Microsoft Edge", "Microsoft Edge"),
    "msedge-beta": ("Microsoft Edge Beta", "Microsoft Edge Beta"),
    "msedge-dev": ("Microsoft Edge Dev", "Microsoft Edge Dev"),
    "msedge-canary": ("Microsoft Edge Canary", "Microsoft Edge Canary"),
    "chromium-system": ("Chromium", "Chromium"),
    "brave": ("Brave Browser", "Brave Browser"),
    "vivaldi": ("Vivaldi", "Vivaldi"),
    "opera": ("Opera", "Opera"),
    "arc": ("Arc", "Arc"),
    "firefox-system": ("Firefox", "firefox"),
    "safari": ("Safari", "Safari"),
}
WINDOWS_PATHS = {
    "chrome": ("Google/Chrome/Application/chrome.exe",),
    "chrome-beta": ("Google/Chrome Beta/Application/chrome.exe",),
    "chrome-dev": ("Google/Chrome Dev/Application/chrome.exe",),
    "chrome-canary": ("Google/Chrome SxS/Application/chrome.exe",),
    "msedge": ("Microsoft/Edge/Application/msedge.exe",),
    "msedge-beta": ("Microsoft/Edge Beta/Application/msedge.exe",),
    "msedge-dev": ("Microsoft/Edge Dev/Application/msedge.exe",),
    "msedge-canary": ("Microsoft/Edge SxS/Application/msedge.exe",),
    "chromium-system": ("Chromium/Application/chrome.exe", "Chromium/chrome.exe"),
    "brave": ("BraveSoftware/Brave-Browser/Application/brave.exe",),
    "vivaldi": ("Vivaldi/Application/vivaldi.exe",),
    "opera": (
        "Opera/opera.exe",
        "Programs/Opera/opera.exe",
        "Opera/launcher.exe",
        "Programs/Opera/launcher.exe",
    ),
    "arc": ("Microsoft/WindowsApps/Arc.exe", "TheBrowserCompany/Arc/Application/Arc.exe"),
    "firefox-system": ("Mozilla Firefox/firefox.exe", "Programs/Mozilla Firefox/firefox.exe"),
}
LINUX_COMMANDS = {
    "chrome": ("google-chrome", "google-chrome-stable"),
    "chrome-beta": ("google-chrome-beta",),
    "chrome-dev": ("google-chrome-unstable",),
    "msedge": ("microsoft-edge", "microsoft-edge-stable"),
    "msedge-beta": ("microsoft-edge-beta",),
    "msedge-dev": ("microsoft-edge-dev",),
    "chromium-system": ("chromium", "chromium-browser"),
    "brave": ("brave-browser", "brave-browser-stable", "brave"),
    "vivaldi": ("vivaldi", "vivaldi-stable"),
    "opera": ("opera",),
    "firefox-system": ("firefox", "firefox-esr"),
}


@dataclass(frozen=True)
class BrowserChoice:
    engine: str
    channel: str | None = None
    executable_path: Path | None = None
    product: str | None = None
    backend: str = "playwright"
    driver_path: Path | None = None

    @property
    def name(self):
        return self.product or (
            "custom-" + self.engine if self.executable_path else self.channel or self.engine
        )


def choices(
    browser=None, *, channel=None, executable_path=None, driver_path=None, environment=None
):
    env = os.environ if environment is None else environment
    selected = browser or env.get("XHH_BROWSER_ENGINE", "auto")
    if selected not in BROWSER_CHOICES:
        raise OperatorError("不支持该浏览器，请查看 xiaoheihe browsers。", "input")
    if browser is None:
        channel = channel or env.get("XHH_BROWSER_CHANNEL") or None
        executable_path = executable_path or env.get("XHH_BROWSER_EXECUTABLE") or None
    if selected == "edge":
        selected = "msedge"
    if selected in NATIVE_BROWSERS:
        if channel:
            raise OperatorError("系统 Firefox 和 Safari 不接受 Chromium channel 参数。", "input")
        if selected == "safari" and sys.platform != "darwin":
            raise OperatorError("Safari 登录只适用于 macOS。", "browser")
        path = Path(executable_path).expanduser() if executable_path else system_browser(selected)
        if not path or not path.is_file():
            raise OperatorError(
                f"未找到 {selected}，请安装浏览器或指定 --executable-path。", "browser"
            )
        driver = driver_path or env.get("XHH_BROWSER_DRIVER")
        driver = Path(driver).expanduser() if driver else browser_driver(selected)
        if not driver or not driver.is_file():
            raise OperatorError(
                f"未找到 {selected} 的驱动，请安装 geckodriver 或指定 --driver-path。", "browser"
            )
        if selected == "safari" and executable_path:
            raise OperatorError("Safari 使用系统驱动；自定义预览版请指定 --driver-path。", "input")
        return [
            BrowserChoice(
                "firefox" if selected == "firefox-system" else "safari",
                executable_path=path,
                product=selected,
                backend="webdriver",
                driver_path=driver,
            )
        ]
    if driver_path:
        raise OperatorError("--driver-path 仅用于 firefox-system 或 safari。", "input")
    if selected in NAMED_BROWSERS:
        if channel:
            raise OperatorError("命名浏览器与 channel 参数不能同时指定。", "input")
        path = Path(executable_path).expanduser() if executable_path else system_browser(selected)
        if not path or not path.is_file():
            raise OperatorError(
                f"未找到 {selected}，可通过 --executable-path 指定安装文件。", "browser"
            )
        return [BrowserChoice("chromium", executable_path=path, product=selected)]
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
        *[
            BrowserChoice("chromium", executable_path=path, product=name)
            for name in NAMED_BROWSERS
            if (path := system_browser(name))
        ],
        BrowserChoice("firefox"),
        BrowserChoice("webkit"),
    ]


def system_browser(channel, *, platform=None, environment=None, home=None):
    """检查标准安装位置，不读取任何浏览器的用户配置或会话。"""
    platform = platform or sys.platform
    env = os.environ if environment is None else environment
    home = Path.home() if home is None else Path(home)
    if channel == "edge":
        channel = "msedge"
    paths = []
    if platform == "darwin" and channel in MAC_APPS:
        app, binary = MAC_APPS[channel]
        paths = [
            root / f"{app}.app/Contents/MacOS/{binary}"
            for root in (Path("/Applications"), home / "Applications", Path("/System/Applications"))
        ]
    elif platform == "win32":
        paths = [
            Path(root) / relative
            for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
            if (root := env.get(variable))
            for relative in WINDOWS_PATHS.get(channel, ())
        ]
        if channel == "arc" and env.get("LOCALAPPDATA"):
            root = Path(env["LOCALAPPDATA"]) / "Microsoft/WindowsApps"
            paths.extend(sorted(root.glob("TheBrowserCompany.Arc_*/Arc.exe")))
    for path in paths:
        if path.is_file():
            return path
    commands = LINUX_COMMANDS.get(channel, ()) if platform.startswith("linux") else ()
    if platform == "win32":
        commands = {
            "chrome": ("chrome.exe",),
            "msedge": ("msedge.exe",),
            "firefox-system": ("firefox.exe",),
            "brave": ("brave.exe",),
            "vivaldi": ("vivaldi.exe",),
            "opera": ("opera.exe",),
            "arc": ("Arc.exe",),
            "chromium-system": ("chromium.exe",),
        }.get(channel, ())
    for command in commands:
        if path := shutil.which(command):
            if channel == "firefox-system" and path == "/snap/bin/firefox":
                native = Path("/snap/firefox/current/usr/lib/firefox/firefox")
                if native.is_file():
                    return native
            return Path(path)
    return None


def browser_driver(browser):
    if browser == "firefox-system" and sys.platform.startswith("linux"):
        binary = system_browser(browser)
        snap_driver = Path("/snap/bin/geckodriver")
        if binary and str(binary).startswith("/snap/firefox/") and snap_driver.is_file():
            return snap_driver
    command = "safaridriver" if browser == "safari" else "geckodriver"
    if path := shutil.which(command):
        return Path(path)
    if browser == "safari" and sys.platform == "darwin":
        path = Path("/usr/bin/safaridriver")
        if path.is_file():
            return path
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
    for channel in (*CHANNELS, *NAMED_BROWSERS, *NATIVE_BROWSERS):
        path = system_browser(channel)
        native = channel in NATIVE_BROWSERS
        driver = browser_driver(channel) if native else None
        result.append(
            {
                "browser": channel,
                "available": bool(path and (driver if native else True)),
                "installed": bool(path),
                "backend": "webdriver" if native else "playwright",
                "driver_available": bool(driver) if native else None,
                "install": "安装对应浏览器；系统 Firefox 另需 geckodriver"
                if native
                else "安装对应浏览器，或指定 --executable-path",
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
        if choice.backend != "playwright":
            raise OperatorError(
                "系统 Firefox 和 Safari 请使用 login --browser 登录；辅助页面使用 Playwright 引擎。",
                "browser",
            )
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
