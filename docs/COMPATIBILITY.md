# 兼容性与验收范围

日期：2026-10-10。适配入口、启动成功、合成页面解析和真实站点读写分别记录。

| 浏览器 | 登录入口 | 本机测试范围 |
|---|---|---|
| Chromium | Playwright 配套运行时或自定义程序 | 缓存程序启动、合成登录和 Cookie 校验流程通过 |
| Chrome | 已安装程序的 `chrome` 通道 | 本机启动与合成登录通过 |
| Edge | 已安装程序的 `msedge` 通道 | 入口存在；本机未安装，实际启动跳过 |
| Firefox | Playwright 配套构建 | 缓存程序与合成登录通过；不等同于系统 Firefox |
| WebKit | Playwright 配套构建 | 缓存程序与合成登录通过；不等同于 Safari |
| 其他 Chromium 程序 | 显式 `--executable-path` | 是否兼容取决于程序版本；不读取浏览器个人资料 |

完整真实网站登录尚未逐浏览器验收。官网导航超时、认证状态和验证码属于各自的验证结果，不能用合成页面测试替代。

CI 配置了 Ubuntu、macOS、Windows 与 Python 3.11／3.12／3.13；浏览器任务在 Linux 安装配套 Chromium、Firefox、WebKit。配置矩阵不等于已完成远端执行。

权限模式检查只在 POSIX 系统执行；Windows 不用 `0600/0700` 数值证明 ACL 安全。所有默认检查使用合成数据和本地服务，不读取真实登录内容。

媒体元信息优先由 Pillow／ffprobe 读取。没有 ffprobe 时，可通过独立浏览器上下文读取视频元信息；需要兼容的视频运行时。
