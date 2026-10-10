# 兼容性与验收范围

日期：2026-10-10。适配入口、启动成功、合成页面解析和真实站点读写分别记录。

| 浏览器 | 登录入口 | macOS 本机 | Linux CI |
|---|---|---|---|
| Chromium | Playwright 配套运行时或自定义程序 | 缓存程序启动、合成登录和 Cookie 校验通过 | 合成登录通过 |
| Chrome | 已安装程序的 `chrome` 通道 | 启动与合成登录通过 | 合成登录通过 |
| Edge | 已安装程序的 `msedge` 通道 | 未安装，启动测试跳过 | 合成登录通过 |
| Firefox | Playwright 配套构建 | 缓存程序与合成登录通过 | 配套构建合成登录通过 |
| WebKit | Playwright 配套构建 | 缓存程序与合成登录通过 | 配套构建合成登录通过 |
| 其他 Chromium 程序 | 显式 `--executable-path` | 取决于程序版本 | 按具体程序验证 |

配套 Firefox 不等同于系统 Firefox，WebKit 不等同于 Safari；登录窗口使用独立浏览器上下文。

## 系统浏览器入口

| 选择 | macOS | Windows | Linux | 连接方式 |
|---|---|---|---|---|
| Chrome／Edge | 支持 | 支持 | 支持 | Playwright 安装通道 |
| Chromium／Brave／Vivaldi／Opera | 支持 | 支持 | 支持 | 命名程序或自定义可执行文件 |
| Arc | 支持 | 支持 | — | 命名程序或 Windows 应用别名 |
| 系统 Firefox、便携 Firefox、Firefox 衍生版 | 支持 | 支持 | 支持 | geckodriver，可自定义程序和驱动 |
| Safari | 支持 | — | — | 系统 safaridriver，需启用远程自动化 |

安装路径覆盖 macOS 系统与用户 Applications、Windows 三类安装目录及 Arc 应用别名、Linux PATH；路径解析在三系统矩阵中使用合成安装目录测试。其他 Chromium 系程序可以用 `--executable-path` 接入，实际兼容性取决于程序的自动化接口。

完整真实网站登录尚未逐浏览器验收。官网导航超时、认证状态和验证码属于各自的验证结果，不能用合成页面测试替代。

GitHub CI 的 Ubuntu、macOS、Windows × Python 3.11／3.12／3.13 九组矩阵已通过。Linux 浏览器任务安装并验证配套 Chromium、Firefox、WebKit；执行记录见 [验证记录](validation.md)。

权限模式检查只在 POSIX 系统执行；Windows 不用 `0600/0700` 数值证明 ACL 安全。所有默认检查使用合成数据和本地服务，不读取真实登录内容。

媒体元信息优先由 Pillow／ffprobe 读取。没有 ffprobe 时，可通过独立浏览器上下文读取视频元信息；需要兼容的视频运行时。
