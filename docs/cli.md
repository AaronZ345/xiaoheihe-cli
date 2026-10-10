# 命令参考

## 浏览器登录

```bash
xiaoheihe-cli browsers
xiaoheihe-cli login --browser chrome
xiaoheihe-cli login --browser edge
xiaoheihe-cli login --browser brave
xiaoheihe-cli login --browser firefox-system --driver-path /path/to/geckodriver
xiaoheihe-cli login --browser safari
```

系统、安装通道、便携程序及驱动配置见 [浏览器登录](browser-login.md)。

## 个人游戏记录和短评

```bash
xiaoheihe games --limit 20
xiaoheihe games --query "游戏名称"
xiaoheihe review list --limit 10                 # 完整本人评分和短评，逐款串行读取
xiaoheihe review list --summary --limit 20       # 游戏名称和个人评分，不补全文本
xiaoheihe review list --offset 20 --limit 20     # 下一页
xiaoheihe review get 570

xiaoheihe review create 570 --score 4 --text "我的短评" --dry-run
xiaoheihe review create 570 --score 4 --text "我的短评"
xiaoheihe review edit 570 --score 5              # 保留完整原正文
xiaoheihe review edit 570 --text "修改后的短评"    # 保留个人评分
xiaoheihe review edit 570 --score 4 --file review.txt --dry-run
xiaoheihe review delete 570 --dry-run
xiaoheihe review delete 570
```

个人评分使用客户端的 **1–5 星整数**。`personal_score` 来自本人评测；社区汇总评分不会代替它。短评正文按原文返回，保留用户自己写的评分表达。

`review list` 的平台参数是小黑盒内部平台标识，默认 `steam`；这些请求全部发往小黑盒。列表分页返回 `next_offset`，平台没有返回是否还有数据时，`has_more` 为 `null`。没有评测会返回 `exists: false`，接口不兼容会明确报错。

修改和删除先读取本人记录，并校验账号和记录身份。修改评分时从帖子详情读取完整原正文，避免覆盖成摘要。`--dry-run` 只读取记录并展示提交计划。

## 兼容命令

以下命令和原有输出格式保留：

```bash
xiaoheihe get 123456 --full
xiaoheihe comments 123456 -p 2 -s 20
xiaoheihe batch 123456 234567
xiaoheihe batch --file ids.txt --full
xiaoheihe creator 123456
xiaoheihe list
xiaoheihe pub "标题" -m "## 正文"             # 默认保存草稿
xiaoheihe pub "标题" --html article.html --publish
xiaoheihe serve --headless                  # 浏览器常驻；前台运行
xiaoheihe status
```

`get/comments/batch/creator/list/pub/serve/status` 也可通过 `python cli.py` 调用。完整评论读取会推进根评论分页，并补齐楼中楼；重复页、游标异常或超过 100 页上限时明确报错，不把截断数据标成完整。批量请求串行执行，失败时停止。

JSON、表格、CSV 和文件输出继续支持：

```bash
xiaoheihe -f json get 123456
xiaoheihe -f table review list --limit 5
xiaoheihe -f csv -o reviews.csv review list --limit 10
```

## 社区操作

```bash
xiaoheihe search "游戏名称" --type post
xiaoheihe search "游戏名称" --type game
xiaoheihe search "话题名称" --type topic
xiaoheihe search "用户名称" --type user
xiaoheihe post list --limit 20
xiaoheihe post get 123456
xiaoheihe post get 123456 --draft
xiaoheihe post create --title "标题" --file article.md --tag 11 --dry-run
xiaoheihe post create --title "标题" --file article.md --tag 11 --publish
xiaoheihe post edit 123456 --title "新标题" --file article.md --tag 11 --publish
xiaoheihe post delete 123456 --dry-run
xiaoheihe post delete 123456 --draft --dry-run
xiaoheihe comment list 123456 --sort latest
xiaoheihe comment create 123456 --text "评论内容" --dry-run
xiaoheihe comment reply 123456 --reply-id 234567 --root-id 234560 --text "回复内容"
```

发文章默认存草稿，加 `--publish` 正式发布。`--tag` 是内容分类 ID，文章默认 `11`；社区用 `--community`，话题用 `--hashtag`。修改或删除帖子只允许本人内容，无法确认作者时停止操作。

新命令默认只在 stdout 输出一份 JSON；登录进度在 stderr。写请求不自动重试。`accepted: true` 表示平台接收了提交；`verified: true` 表示读取核实了结果。`verified: false` 或网络超时不能当成最终写入成功，也不要盲目重复发布。


文章或草稿提交后会有界读回核验标题、正文、ID 和作者。平台标题索引可能延迟更新，程序只重试读回，不重复提交写请求；校验仍不一致时保留 `verified=false`。


## 媒体与更多发布方式

```bash
xiaoheihe-cli doctor
xiaoheihe-cli doctor --verify-login
xiaoheihe-cli profile --limit 10
xiaoheihe-cli feed --limit 10
xiaoheihe-cli media inspect /path/to/photo.png
xiaoheihe-cli media upload /path/to/photo.png --dry-run
xiaoheihe-cli post create --kind image_text --title "标题" --image /path/to/photo.png --text "正文" --dry-run
xiaoheihe-cli post create --title "文章" --file article.md --community "社区一" --community "社区二" --hashtag "话题" --dry-run
xiaoheihe-cli video create /path/to/video.mp4 --title "标题" --cover /path/to/cover.png
xiaoheihe-cli comment create POST_ID --image /path/to/photo.png --dry-run
xiaoheihe-cli comment reply POST_ID --target-text "目标评论的完整正文" --text "回复" --dry-run
```

文章中的 Markdown／HTML 本地图片与独立绝对路径会按原位置上传；代码示例里的路径不会当作图片。`--file` 正文内的相对图片以正文文件目录解析。额外图片用重复的 `--image`，社区最多 2 个，话题最多 5 个。

图片、视频会先检查格式和元信息；缺文件、无效社区或重复话题不进入发布。上传确认完成后才提交内容，任一步失败都不自动重复上传或提交。

视频没有平台草稿功能。`video create` 默认预览，只有 `--publish` 且未指定 `--dry-run` 才实际发布；文章和图文仍默认保存草稿。

`doctor` 默认仅检查运行时和会话文件元信息。`skill install` 安装发行包自带的技能，拒绝覆盖其他来源。MCP 的命令和参数见 [MCP](MCP.md)。
