# 浏览器登录

```bash
xiaoheihe browsers
xiaoheihe login --browser              # 自动选择
xiaoheihe login --browser chromium
xiaoheihe login --browser chrome
xiaoheihe login --browser edge
xiaoheihe login --browser firefox
xiaoheihe login --browser webkit
xiaoheihe login --browser brave
xiaoheihe login --browser vivaldi
xiaoheihe login --browser opera
xiaoheihe login --browser arc
xiaoheihe login --browser firefox-system
xiaoheihe login --browser safari
```

`--browser` 不带名称时自动选择：配套 Chromium、本机 Chrome／Edge、已安装的 Chromium 系浏览器、配套 Firefox／WebKit。系统 Firefox 和 Safari 用名称选择。指定名称后保留该选择，启动错误会说明安装或驱动要求。

| 选择 | 使用的运行时 | 安装方式 |
|---|---|---|
| `chromium` | 当前 Playwright 配套 Chromium | `playwright install chromium` |
| `chrome` | 本机 Google Chrome | 使用已安装的 Chrome |
| `edge` / `msedge` | 本机 Microsoft Edge | 使用已安装的 Edge |
| `chromium-system` | 本机 Chromium | 使用系统安装或便携程序 |
| `brave` / `vivaldi` / `opera` | 本机 Chromium 系浏览器 | 自动识别 macOS、Windows、Linux 的常用安装位置 |
| `arc` | 本机 Arc | macOS／Windows 安装位置及 Windows 应用别名 |
| `firefox` | Playwright 配套 Firefox | `playwright install firefox` |
| `firefox-system` | 本机 Firefox + geckodriver | 安装 Firefox 和 geckodriver，或指定程序与驱动路径 |
| `webkit` | Playwright 配套 WebKit | `playwright install webkit` |
| `safari` | macOS Safari + safaridriver | macOS 自带驱动，首次需启用远程自动化 |

`firefox` 和 `webkit` 使用 Playwright 配套版本；`firefox-system` 和 `safari` 使用各自的 WebDriver。运行时要求见 [Playwright](https://playwright.dev/python/docs/browsers)、[Mozilla](https://firefox-source-docs.mozilla.org/testing/geckodriver/Usage.html) 和 [Safari](https://www.selenium.dev/documentation/webdriver/browsers/safari/) 官方说明。

Safari 首次使用时，在开发菜单开启“允许远程自动化”，再执行 `safaridriver --enable` 完成系统授权。登录程序会提示所需设置。Safari 使用桌面窗口。

## 自定义浏览器

其他 Chromium 系浏览器或单独安装的 Chromium 可以指定可执行文件：

```bash
xiaoheihe login --browser chromium --executable-path /path/to/browser
xiaoheihe login --browser chrome-beta
xiaoheihe login --browser chromium --channel msedge-beta
xiaoheihe login --browser brave --executable-path /path/to/brave
xiaoheihe login --browser firefox-system --executable-path /path/to/firefox --driver-path /path/to/geckodriver
```

Chromium 系的自定义程序需要支持 Chromium 自动化接口；Firefox 便携版和衍生版本使用 `firefox-system` 与对应的 geckodriver。Safari 使用系统驱动。`--channel` 与 `--executable-path` 互斥，支持所在系统提供的 Chrome／Edge stable、beta、dev、canary 通道。

可通过 `XHH_BROWSER_ENGINE`、`XHH_BROWSER_CHANNEL`、`XHH_BROWSER_EXECUTABLE`、`XHH_BROWSER_DRIVER` 配置；CLI 指定的名称和路径优先。SDK 和守护进程共用登录会话，少量辅助页面使用 Playwright 引擎。`xiaoheihe browsers` 显示配套运行时、系统浏览器及驱动的安装状态。

SDK 和 REST 的帖子、评论及创作者 HTTP 查询直接复用会话；需要网页拦截的辅助接口再按需启动页面。

macOS 识别系统和用户 Applications 目录；Windows 识别 Program Files、Program Files (x86)、LocalAppData 和 Arc 应用别名；Linux 识别 PATH 中的发行版命令。便携版或其他安装目录可用 `--executable-path`。Linux 桌面登录需要显示服务；Firefox Snap 可指定匹配的 Snap geckodriver。

## 登录过程

网页登录会打开独立浏览器上下文。用户在小黑盒官方页面完成手机号、密码、验证码或二次验证；CLI 在账号身份校验通过后保存会话。程序不读取已安装浏览器的用户配置、历史记录或已有会话。

没有桌面显示服务时使用 `xiaoheihe login` 扫码，或 `xiaoheihe login --cookie-file /path/to/cookie.txt` 导入并校验会话。浏览器启动错误与认证失败分别处理，错误输出不会包含底层请求或凭据。

默认会话位置：macOS 为 `~/Library/Application Support/xiaoheihe-cli/session.json`，Windows 为 `%LOCALAPPDATA%\xiaoheihe-cli\session.json`，Linux 为 `$XDG_CONFIG_HOME/xiaoheihe-cli/session.json`（默认 `~/.config`）。`XHH_OPERATOR_HOME` 可指定运行时目录。二维码 PNG 为临时文件，命令退出时删除；平台要求安全验证时由用户在官方页面完成。

二维码输出使用独占的新临时文件；自定义路径已存在时拒绝覆盖。生成失败、失效和命令退出时会清理本次创建的图片。
