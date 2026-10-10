# 小黑盒接口契约

核对日期：2026-10-10。

网页契约来自当前官方页面的 JS 模块；个人评测写入契约来自官网链接的 Android 客户端 1.3.396。客户端 APK SHA256 为 `8553e8270b8e4d2ca8fc3037b9d6f98f1eaae9697a8fd322fc6de78b41e9d56e`。不保存客户端文件、登录材料或个人读取结果到 Git。

| 操作 | 路径 | 参数或响应要点 |
|---|---|---|
| 账号身份 | GET `/account/restore_login` | 有效 `profile.heybox_id` 或 `account_detail.userid`；公开帖子可读不是身份凭证 |
| 扫码登录 | GET `/account/get_qrcode_url/`、`/account/qr_state/` | App 确认；等待、已扫描、成功、过期和二次验证分别处理 |
| 个人游戏记录 | GET `/account/game_list/` | `userid/offset/limit/sort/q` |
| 个人评测列表 | GET `/account/my_comment_list` | `userid/platform/offset/limit`；默认平台 `steam`，`pc` 会返回空列表 |
| 本人单款评测 | GET `/bbs/app/link/game/comment/mine` | `appid`；`exists/impression_score/link` |
| 完整正文 | GET `/bbs/app/link/tree` | `link.text` 为文本块序列化 JSON，`description` 是摘要，修改时不能用摘要替代 |
| 创建、修改短评 | POST `/bbs/app/api/link/post` | 表单：`appid/score/text/game_impression_post_type=2/link_tag=3`；修改再加 `edit=1/link_id` |
| 删除短评或帖子 | POST `/bbs/app/link/delete` | `link_id`；操作前确认本人记录 |
| 评论和回复 | POST `/bbs/app/comment/create` | `link_id/text/is_cy=0/reply_id/root_id`；普通评论两个 ID 为 `-1` |
| 根评论分页 | GET `/bbs/app/link/tree` | `page/is_first/index/owner_only/limit`，兼容参数 `offset/sort_filter`；`has_more_floors` 控制根楼层翻页 |
| 楼中楼 | GET `/bbs/app/comment/sub/comments` | `root_comment_id/lastval`；`lastval` 使用最后一条已读取评论的 ID；响应 `comments/has_more`，不要求返回游标字段 |
| 帖子、用户搜索 | GET `/bbs/app/api/general/search/v1` | 关键词使用 `q`；`search_type` 分别为 `link`、`user`，不能把 CLI 的 `post` 直接传入 |
| 话题、游戏搜索 | GET `/bbs/app/api/search/topic`、`/game/search/` | `q/offset/limit`；响应分别包含 `topics`、`games` |
| 创作者列表 | GET `/bbs/app/author/concept/article/list` | `article_type=all/artilce_state=all/sort_filter=create_at/offset/limit`；`artilce_state` 是平台原有拼写 |
| 创作者统计 | GET `/bbs/app/author/concept/article/data` | `link_id`；对应本人可用文章 |

个人评测列表中的 `score` 是社区汇总评分，`comment_score` 才是本人的评分。本人单款评测的 `impression_score` 为个人 1–5 星整数；纯文本短评正文编码为 `[{"type":"text","text":"正文"}]`。修改保留原文本块。

签名按当前公开网页协议生成，每次请求重新计算，不能把一条请求的签名复用到其他路径。网页写接口使用 Workshop 附加签名。客户端契约不等于稳定的公开 API。

接口测试使用合成数据，覆盖正文保留、身份限制、分页推进、失败停止和无重复提交。线上功能由平台的登录状态、账号权限和安全验证决定。服务端接受提交但回读失败时返回 `accepted=true, verified=false`。没有服务端响应的写请求报告结果未知，不自动重发。

本人草稿编辑数据通过 GET `/bbs/app/link/edit/info` 按 `link_id` 读取；草稿删除请求带 `draft=1`。标题字段可能出现短暂的读回延迟，写操作不会因此重复提交。

搜索参数对照当前官方 [搜索页面模块](https://static.max-c.com/static/heybox/webapp/@heybox-spa/website/app/index-Cj-EoIUs.js) 和 [接口模块](https://static.max-c.com/static/heybox/webapp/@heybox-spa/website/app/index-0X6Ad2t1.js) 核实；发布后文件名可能变化。验证搜索时检查实际结果，不能仅凭 `status=ok` 判断参数正确。

2026-10-10 复核官方 [帖子模块](https://static.max-c.com/static/heybox/webapp/@heybox-spa/website/app/index-BRmpZOWP.js)、[创作者列表模块](https://static.max-c.com/static/heybox/webapp/@heybox-spa/website/app/index-BQE1-KRt.js) 和 [统计模块](https://static.max-c.com/static/heybox/webapp/@heybox-spa/website/app/index-CvYPsrmH.js)，补齐分页与楼中楼游标契约。已有会话的 HTTP 查询不需要预先导航官网首页。


## 媒体与发布

- 上传预检：POST `/bbs/app/api/qcloud/cos/upload/info/v2`，`file_infos/scope=bbs/need_cache`，返回 bucket、region 和对象 key。
- 临时凭据：POST `/bbs/app/api/qcloud/cos/upload/token/v2`，`bucket/keys/mimetypes/is_multipart_upload`。凭据只在内存中用于 HTTPS COS 请求，不写入文件或接口结果。
- 上传确认：POST `/bbs/app/api/qcloud/cos/upload/callback/v2`，查询 `is_finished=true`，表单 `keys`，读取 `preview_urls/thumbs`。单对象上传上限 5 GiB，不自动重传。
- 选择社区／话题：GET `/bbs/app/api/post_editor/topic_selection/search`，`q/only_hashtag=0`；按 `search_type` 与准确名称解析。发布使用 `topic_ids` 和 JSON `hashtags`。
- 图文分类 `27`，默认动态分类 `28`；文章分类 `11`。文章 HTML 保留图片位置，同时提供图片元信息块。平台可能转换 CDN 地址和 HTML 属性顺序，回读按同一资源标识与正文语义核验。
- 视频：POST `/bbs/app/api/video-link/post`，`video_url/video_thumb/video_duration/video_duration_desc/video_cos_provider=tencent`；正文为普通文本。平台明确拒绝视频草稿，正式发布必须显式选择。
- 图片评论使用 `imgs`，多个地址以分号连接。正文定位回复先完整读取有界评论，不选择重复正文的首个候选。

网页协议由平台当前上传、编辑器和帖子模块核对；这些接口可能变化，发布结果仍须检查 `accepted/verified`。
