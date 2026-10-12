<div align="center">

# xiaoheihe-cli

在终端查询游戏记录和个人短评，管理小黑盒社区内容。支持 CLI、Python SDK、REST API、MCP 和 Agent Skill。

[![CI](https://github.com/AaronZ345/xiaoheihe-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/AaronZ345/xiaoheihe-cli/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-%E2%89%A53.11-3776AB)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

[安装](#安装) · [常用命令](#常用命令) · [助手接入](#助手接入) · [浏览器](#浏览器) · [文档](#文档) · [开发](CONTRIBUTING.md)

</div>

## 能做什么

| 功能 | 内容 |
|---|---|
| 个人游戏与评测 | 游戏记录、按名称查询、本人评分与完整短评；创建、修改、删除个人评测 |
| 社区查询 | 帖子、游戏、话题、用户搜索；首页、本人主页、帖子、评论与楼中楼 |
| 内容发布 | 图文和文章、本地图片、Markdown 内嵌图片；最多 2 个社区、5 个话题 |
| 视频 | 本地视频上传、自动或指定封面、正式发布；视频默认仅预览 |
| 评论与回复 | 文字和图片评论；按 ID 或完整正文定位目标，重复正文不自动选择 |
| 批量与导出 | 评论分页、批量帖子、创作者数据、JSON／表格／CSV、文件输出 |
| 助手接入 | 18 个 MCP 工具、Agent Skill、ChatGPT Dots、本地诊断与 REST 服务 |
| 浏览器登录 | macOS／Windows／Linux 的 Chrome、Edge、Chromium、Brave、Vivaldi、Opera、Firefox；macOS Safari、macOS／Windows Arc；支持便携程序和自定义路径 |

## 安装

需要 **Python 3.11 或更新版本**。直接安装：

```bash
uv tool install git+https://github.com/AaronZ345/xiaoheihe-cli.git
xiaoheihe-cli --version
xiaoheihe-cli doctor
```

从源码开发：

```bash
git clone https://github.com/AaronZ345/xiaoheihe-cli.git
cd xiaoheihe-cli
uv sync
uv run xiaoheihe-cli --help
uv run xiaoheihe-cli doctor
```

本地 wheel 也可以用 `uv tool install /path/to/xiaoheihe_cli-0.1.0-py3-none-any.whl` 安装。`xiaoheihe` 是兼容命令别名。

## 常用命令

### 查询记录与社区

```bash
xiaoheihe-cli login
xiaoheihe-cli login --browser chrome
xiaoheihe-cli auth status
xiaoheihe-cli games --limit 10
xiaoheihe-cli games --query "游戏名称"
xiaoheihe-cli review list --limit 2
xiaoheihe-cli review list --summary --limit 20
xiaoheihe-cli review get 570
xiaoheihe-cli search "游戏名称" --type post
xiaoheihe-cli feed --limit 10
xiaoheihe-cli post get POST_ID
xiaoheihe-cli comment list POST_ID --sort latest
```

个人评分是小黑盒本人的 **1–5 星整数**，`personal_score` 不使用社区汇总评分。完整短评从本人评测正文读取；连续读取遇到验证码时停止该项请求。

### 编辑与发布

```bash
xiaoheihe-cli review edit 570 --score 4 --dry-run
xiaoheihe-cli post create --kind image_text --title "标题" --text "正文" --image /path/to/photo.png --dry-run
xiaoheihe-cli post create --kind article --title "标题" --file article.md --community "准确社区名称" --hashtag "准确话题名称" --dry-run
xiaoheihe-cli video create /path/to/video.mp4 --title "标题" --cover /path/to/cover.png
xiaoheihe-cli comment create POST_ID --text "评论" --image /path/to/photo.png --dry-run
xiaoheihe-cli comment reply POST_ID --target-text "目标评论完整正文" --text "回复" --dry-run
```

文章和图文移除 `--dry-run` 后保存草稿，正式发布再加 `--publish`。平台不支持视频草稿；视频未加 `--publish` 时只预览，明确发布才上传和提交。未提供的个人评分或正文会保留；帖子编辑和删除先核实作者。

## 助手接入

### ChatGPT Dots

ChatGPT Dots 可通过已连接的电脑调用 `xiaoheihe-cli`。CLI 和技能需安装在该电脑上，并授予 Dot 访问权限。使用时电脑需在线，ChatGPT 桌面应用需保持打开。[电脑连接文档](https://learn.chatgpt.com/docs/dots/computers-and-apps)

Dot 读取技能后可调用本机命令，例如：

> 使用这台电脑上的 xiaoheihe-cli，列出我最近玩过的 10 款游戏，包含我的评分。

### Agent Skill

Agent Skill 随 wheel 和源码包提供：

```bash
xiaoheihe-cli skill install
```

安装到当前 Codex home 的技能目录；已有其他来源或符号链接时拒绝覆盖。技能内容位于 [skills/xiaoheihe-cli/SKILL.md](skills/xiaoheihe-cli/SKILL.md)。

### MCP

启用 MCP：

```bash
uv sync --extra mcp
uv run xiaoheihe-cli mcp
uv run xiaoheihe-cli mcp --transport streamable-http --port 8001
```

MCP 写工具默认 `dry_run=true`。实际提交需显式设置 `dry_run=false`；图文和文章的公开发布还需设置 `draft=false`。工具清单、参数和客户端配置见 [MCP](docs/MCP.md)。

## 浏览器

网页登录可用已安装的 Chrome 或 Edge；需要配套引擎时，在工具环境运行 `playwright install chromium`，源码环境执行 `uv run playwright install chromium firefox webkit`。这些操作不读取日常浏览器的个人资料。

```bash
xiaoheihe-cli login --browser chrome
xiaoheihe-cli login --browser brave
xiaoheihe-cli login --browser firefox-system
xiaoheihe-cli login --browser safari
```

更多浏览器可用 `login --browser brave|vivaldi|opera|arc|firefox-system|safari` 选择；安装路径、系统 Firefox 驱动和 Safari 首次设置见 [浏览器登录](docs/browser-login.md)。

## 结果与诊断

`accepted` 表示平台接收，`verified` 表示读回核验。结果未知时不自动重复上传、发布或评论。未知数值保持 `null`；分页异常、限流、认证与验证码有明确错误，不能把失败当作空结果或完整读取。

`doctor` 默认只检查运行时和会话文件元信息；显式 `doctor --verify-login` 才核验账号。会话使用独立的本机应用目录；macOS/Linux 下目录和文件权限分别为 `0700/0600`。账号凭据、个人记录、浏览器资料和媒体文件不进入仓库或发行包。

## 文档

| 文档 | 用途 |
|---|---|
| [命令参考](docs/cli.md) | 查询、编辑、媒体、兼容命令和输出格式 |
| [浏览器登录](docs/browser-login.md) | 引擎、安装、独立登录窗口和自定义路径 |
| [MCP](docs/MCP.md) | 18 个工具与 stdio／Streamable HTTP 配置 |
| [SDK、REST 与 Docker](docs/integrations.md) | 接口调用和本地部署 |
| [接口契约](docs/api-contract.md) | 平台字段、分页、上传和签名 |
| [兼容性](docs/COMPATIBILITY.md) | 浏览器及系统测试范围 |
| [验证记录](docs/validation.md) | 已完成的实测与边界 |
| [开发指南](CONTRIBUTING.md) | 统一验收、构建和发布 |

## 许可证

非官方小黑盒工具，采用 [MIT License](LICENSE)。
