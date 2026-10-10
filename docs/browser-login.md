# 浏览器登录

```bash
xiaoheihe browsers
xiaoheihe login --browser              # 自动选择
xiaoheihe login --browser chromium
xiaoheihe login --browser chrome
xiaoheihe login --browser edge
xiaoheihe login --browser firefox
xiaoheihe login --browser webkit
```

`--browser` 不带名称兼容原有用法。自动选择依次尝试 Chromium、Chrome、Edge、Firefox 和 WebKit。明确指定浏览器时，启动失败会直接说明原因，不切换为其他浏览器。

| 选择 | 使用的运行时 | 安装方式 |
|---|---|---|
| `chromium` | 当前 Playwright 配套 Chromium | `playwright install chromium` |
| `chrome` | 本机 Google Chrome | 使用已安装的 Chrome |
| `edge` / `msedge` | 本机 Microsoft Edge | 使用已安装的 Edge |
| `firefox` | Playwright 配套 Firefox | `playwright install firefox` |
| `webkit` | Playwright 配套 WebKit | `playwright install webkit` |

Firefox 和 WebKit 使用 Playwright 的配套版本，系统 Firefox 和 Safari 不属于这两个选项的运行时。浏览器与 Playwright 的版本配套关系见 [官方说明](https://playwright.dev/python/docs/browsers)。

## 自定义浏览器

其他 Chromium 系浏览器或单独安装的 Chromium 可以指定可执行文件：

```bash
xiaoheihe login --browser chromium --executable-path /path/to/browser
xiaoheihe login --browser chrome-beta
xiaoheihe login --browser chromium --channel msedge-beta
```

自定义文件需要与所选引擎和 Playwright 兼容；不能把系统 Safari 当作 WebKit 可执行文件，普通系统 Firefox 也不保证兼容。`--channel` 只用于 Chromium 系浏览器，与 `--executable-path` 互斥。支持 Chrome/Edge 的 stable、beta、dev 和 canary 通道。

SDK 和守护进程也使用同一启动逻辑，可通过 `XHH_BROWSER_ENGINE`、`XHH_BROWSER_CHANNEL`、`XHH_BROWSER_EXECUTABLE` 配置。CLI 显式指定的浏览器优先于环境配置。`xiaoheihe browsers` 检查配套运行时和本机标准安装位置，不读取浏览器的个人资料。

## 登录过程

网页登录会打开独立浏览器上下文。用户在小黑盒官方页面完成手机号、密码、验证码或二次验证；CLI 在账号身份校验通过后保存会话。程序不读取已安装浏览器的用户配置、历史记录或已有会话。

没有桌面显示服务时使用 `xiaoheihe login` 扫码，或 `xiaoheihe login --cookie-file /path/to/cookie.txt` 导入并校验会话。浏览器启动错误与认证失败分别处理，错误输出不会包含底层请求或凭据。

默认会话位置：macOS 为 `~/Library/Application Support/xiaoheihe-cli/session.json`，Linux 使用用户配置目录。`XHH_OPERATOR_HOME` 可指定运行时目录。二维码 PNG 为临时文件，命令退出时删除；平台要求安全验证时由用户在官方页面完成。

二维码输出使用独占的新临时文件；自定义路径已存在时拒绝覆盖。生成失败、失效和命令退出时会清理本次创建的图片。
