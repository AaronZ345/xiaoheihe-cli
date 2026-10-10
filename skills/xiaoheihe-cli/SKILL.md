---
name: xiaoheihe-cli
description: 查询小黑盒游戏记录、本人评分和完整短评，以及社区帖子、评论与首页；按明确授权编辑或发布内容，支持图片、视频和本地 MCP。
metadata:
  origin: local
  owner: aaron
---

# 小黑盒 CLI

使用 `xiaoheihe-cli`，`xiaoheihe` 是兼容别名。排错先用 `doctor`，默认只检查运行时和文件元信息；只有显式 `doctor --verify-login` 才核验账号。不要读取其他浏览器的凭据或输出会话文件。

## 查询与操作

- 游戏记录：`games --limit <n>`，按名称用 `--query`。
- 本人评分与完整短评：`review list`、`review get <appid>`；`review list --summary` 仅取摘要。个人评分为 1–5 星整数。
- 编辑短评：`review create/edit/delete <appid>`，可先加 `--dry-run`。只改评分时保留原正文；只改正文时保留原评分。
- 社区查询：`search --type post|game|topic|user`、`feed`、`profile`、`post get <id>`、`comment list <id>`。
- 发布文章或图文：`post create --kind article|image_text --title <标题> --file <正文>`；`--image` 可重复，文章支持正文中的本地图片。社区用 `--community`，话题用 `--hashtag`。
- 视频：`video create <文件> --title <标题> --cover <封面>`。默认仅预览，正式发布加 `--publish`；平台不支持视频草稿。
- 评论与回复：`comment create/reply <post-id>`；图片用 `--image`，回复可用明确的 `--reply-id/--root-id` 或 `--target-text`。相同正文有多个结果时不自动选择。

不确定参数时运行对应命令 `--help`。编辑与删除按 ID 核实作者、游戏或帖子身份；不要把名称搜索的第一个候选当作已确定目标。用户已明确授权的操作直接执行，不重复请求确认。

## 登录、媒体与结果

首次使用 `login` 扫码，或 `login --browser chromium|chrome|edge|firefox|webkit` 打开独立的官方窗口。用户自行完成密码和验证码；不索取这些内容。

`media inspect <文件>` 不需要登录或上传。`media upload` 只在用户明确要求时上传媒体。只有需要提交的有效文件才进入上传，社区或话题无效时不继续发布。

检查 `accepted/verified`：接收和回读核验是不同状态。认证、验证码、限流或分页异常时停止该项操作；写入结果未知时先读取核实，不自动重发。开发、示例与默认测试使用合成数据，不把真实账号内容写进仓库或发行包。

本地 MCP 入口为 `xiaoheihe-cli mcp`，需要安装 `mcp` extra。写工具默认 `dry_run=true`；用户明确要求实际提交时用 `dry_run=false`，图文和文章的公开发布再设 `draft=false`。视频只支持正式发布，仍默认预览。CLI、SDK、REST 和 MCP 复用同一操作层。
