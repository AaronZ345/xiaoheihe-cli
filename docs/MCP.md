# MCP 接入

需要安装 `mcp` 可选依赖。源码环境使用 `uv sync --extra mcp`；wheel 可用 `uv tool install --with "mcp>=1.20,<2" /path/to/xiaoheihe_cli-0.1.0-py3-none-any.whl` 安装。

## 连接

stdio 客户端配置：

```json
{
  "mcpServers": {
    "xiaoheihe-cli": {
      "command": "xiaoheihe-cli",
      "args": ["mcp"]
    }
  }
}
```

源码环境可把命令设为 `uv`，参数设为 `run --directory /path/to/xiaoheihe-cli --extra mcp xiaoheihe-cli mcp`。

Streamable HTTP：

```bash
xiaoheihe-cli mcp --transport streamable-http --port 8001
```

地址为 `http://127.0.0.1:8001/mcp`，只监听本机。stdio 的 stdout 仅用于协议消息，进度和诊断在 stderr。

## 社区与登录工具

| 工具 | 参数与用途 |
|---|---|
| `check_login_status` | 核验当前身份；不返回会话凭据 |
| `interactive_login` | `browser/timeout/executable_path/driver_path`，打开所选浏览器的独立官方登录窗口 |
| `get_login_qr_code` | `timeout`，立即返回 PNG 二维码，后台等待确认 |
| `get_user_profile` | `pageSize`，本人主页与动态 |
| `get_home_content` | `limit/offset`，首页内容 |
| `search_content` | `keyword/kind/limit/offset`，帖子、游戏、用户或话题 |
| `get_post_detail` | `postId`，正文、图片和评论 |
| `publish_content` | `title/content/images/communities/tags`，图文内容 |
| `publish_article` | `title/content/communities/tags/images`，Markdown、HTML 和本地图片 |
| `publish_video` | `videoPath/title/content/coverImagePath/communities/tags`，视频与封面 |
| `post_comment` | `postId/content/images`，文字或图片评论 |
| `reply_comment` | `postId/targetCommentContent/content`，按正文定位回复 |

社区最多 2 个，话题最多 5 个；名称需准确且不能重复。重复的评论正文不会自动选择目标，改用 CLI／REST 的明确评论 ID。

二维码确认后，用 `check_login_status` 再核验。二维码仅临时保留，等待结束或取消后清理；密码和验证码由用户在官方界面完成。

## 游戏与个人评测工具

| 工具 | 用途 |
|---|---|
| `get_personal_games` | `limit/offset/query`，个人游戏记录 |
| `list_personal_reviews` | `limit/offset/summary`，本人评分与短评列表 |
| `get_personal_review` | `appid`，单款完整短评 |
| `create_personal_review` | `appid/score/text`，创建评测 |
| `edit_personal_review` | `appid/score/text`，未指定字段保留 |
| `delete_personal_review` | `appid`，核实身份后删除 |

个人评分为 1–5 星整数。删除工具标记为破坏性操作；只读工具和写入工具有独立的 MCP 注解。

## 写入规则

写工具默认 `dry_run=true`，预检文件、读取已有记录并展示计划，不上传媒体或提交内容。用户明确要求实际操作时设 `dry_run=false`。

图文和文章默认 `draft=true`，公开发布设 `draft=false`。平台不支持视频草稿，视频默认 `draft=false` 但仍默认预览；正式提交需要明确的 `dry_run=false`。评论和个人评测会对外生效，调用前须有用户对应内容的授权。

`accepted=true` 不等于回读成功；只有 `verified=true` 才表示核验通过。验证码、认证、限流、分页或上传异常时停止，不自动重复写入。各接口与 CLI 使用同一操作层。
