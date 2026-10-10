# SDK、REST 与 Docker

## Python SDK

```python
from xiaoheihe import XiaoheiheClient, Operator

async with XiaoheiheClient(headless=True) as client:
    post = await client.get_post("123456", full=True)

async with Operator() as operator:
    reviews = await operator.reviews(limit=5)
    preview = await operator.write_review("570", score=4, content="示例短评", dry_run=True)
```

原有 `get_post/get_comments/batch_get/get_creator_data/get_my_articles/publish/publish_markdown` 保留。`Operator` 提供新的游戏、个人评测、搜索、帖子和评论操作，两种客户端使用同一工具会话。媒体、首页、个人主页和视频操作通过 `Operator` 调用。

SDK 直接调用 `publish()` 时传入最终 HTML；需要格式转换时用 `publish_markdown()` 或 `publish_content()`。浏览器配置见 [浏览器登录](browser-login.md)。

## REST API

```bash
xiaoheihe api --port 8010
```

默认监听本机 `127.0.0.1`，接口文档位于 `http://127.0.0.1:8010/docs`。

| 路径 | 方法与用途 |
|---|---|
| `/api/post/{post_id}` | GET：帖子数据 |
| `/api/post/{post_id}/comments` | GET：评论分页 |
| `/api/post/{post_id}/full` | GET：完整帖子和评论 |
| `/api/posts/batch` | POST：串行读取并返回结果，失败即停 |
| `/api/games` | GET：个人游戏记录 |
| `/api/reviews` | GET：个人评测列表 |
| `/api/reviews/{appid}` | GET / POST / PATCH / DELETE：个人评测读写 |
| `/api/search` | GET：社区搜索 |
| `/api/feed` | GET：首页内容 |
| `/api/profile` | GET：本人主页 |
| `/api/media/upload` | POST：上传指定本地媒体，可预检 |
| `/api/videos` | POST：视频与封面，默认预览 |
| `/api/posts` | GET / POST：本人帖子、文章与草稿 |
| `/api/posts/{post_id}` | PATCH / DELETE：修改、删除本人帖子 |
| `/api/posts/{post_id}/comments` | POST：发表评论或回复 |

评测写入 JSON 使用 `score/text/dry_run`；文章使用 `title/text/tag/draft/dry_run/images/communities/hashtags/post_kind`；评论使用 `text/reply_id/root_id/target_text/images/dry_run`。普通评论的两个回复 ID 均为 `-1`，楼中楼回复可同时提供两个 ID，或使用 `target_text` 精确定位正文。

`accepted` 和 `verified` 含义与 CLI 一致。认证失败、验证码和限流分别返回明确的状态，不把请求提交成功当作最终写入已验证。

## Docker

```bash
docker compose build
docker compose run --rm crawler-api xiaoheihe login
docker compose up
```

Compose 仅将端口暴露到本机。会话默认保存在 Docker 管理的 `session-data` 卷，首次创建时继承镜像中应用用户的目录权限。需要绑定已有会话目录时，通过 `XHH_OPERATOR_SESSION_DIR` 指定绝对路径，并确保该目录允许容器中的应用用户访问；会话不加入 Git 或镜像。

容器默认安装 Chromium。使用其他引擎时，增加对应的 Playwright 浏览器和系统依赖。网页登录需要图形显示服务，终端环境优先扫码。运行时会话和读取结果不应加入镜像或仓库。


## 媒体 SDK

```python
async with Operator() as operator:
    image = await operator.upload_media("/path/to/photo.png", dry_run=True)
    article = await operator.write_post("标题", "正文", images=["/path/to/photo.png"],
                                       communities=["准确社区名称"], hashtags=["准确话题名称"], dry_run=True)
    video = await operator.write_video("标题", "/path/to/video.mp4", cover="/path/to/cover.png", dry_run=True)
    reply = await operator.comment("POST_ID", "回复", target_text="目标评论完整正文", dry_run=True)
```

`write_video` 正式提交不支持 `draft=true`。图文可指定 `post_kind="image_text"`，默认是文章。`feed()` 与 `profile()` 分别读取首页和本人主页。上传凭据只在内存中使用，接口结果不会回传它们。
