import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .auth import import_cookies, login_browser, login_qr, verify
from .browsers import BROWSER_CHOICES, CHANNELS, inventory
from .compat import legacy_command, run_legacy
from .errors import OperatorError
from .http import HeyboxAPI
from .output import render
from .service import Operator, present_review
from .session import SessionStore


def positive(value):
    number = int(value)
    if number < 1 or number > 600:
        raise argparse.ArgumentTypeError("必须是 1 到 600 的整数。")
    return number


def offset(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("偏移量不能为负数。")
    return number


def pagination(parser):
    parser.add_argument("--offset", type=offset, default=0)
    parser.add_argument(
        "--limit", type=positive, default=20, choices=range(1, 101), metavar="1..100"
    )


def content_options(parser, *, required=True):
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--text", help="正文或评论文本；发文章时支持 Markdown")
    group.add_argument("--file", type=Path, help="UTF-8 正文文件")


def selections_options(parser):
    parser.add_argument(
        "--community", action="append", default=[], help="准确社区名称，可重复，最多 2 个"
    )
    parser.add_argument(
        "--hashtag", action="append", default=[], help="准确话题名称，可重复，最多 5 个"
    )


def parser():
    class StrictParser(argparse.ArgumentParser):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, allow_abbrev=False)

    root = StrictParser(
        prog="xiaoheihe-cli",
        description="小黑盒操作器：登录、个人游戏记录与评测、社区帖子和评论",
        epilog="兼容命令：get / comments / batch / creator / list / pub / serve / status；支持 JSON、table、CSV、文件输出、Python SDK 和 REST API。使用对应命令 --help 查看参数。",
    )
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("-f", "--format", choices=("json", "table", "csv"), default="json")
    root.add_argument("-o", "--output", type=Path)
    sub = root.add_subparsers(dest="command", required=True, parser_class=StrictParser)
    login = sub.add_parser("login", help="扫码登录，或打开官方网页登录")
    modes = login.add_mutually_exclusive_group()
    modes.add_argument(
        "--browser",
        nargs="?",
        const="auto",
        choices=BROWSER_CHOICES,
        help="选择网页登录浏览器；不指定名称时自动选择",
    )
    modes.add_argument(
        "--cookie-file", type=Path, help="从文件导入并校验会话；不接受命令行密码或 Cookie"
    )
    login.add_argument("--timeout", type=positive, default=180)
    login.add_argument("--qr-file", type=Path, help="临时二维码 PNG 路径；命令结束时删除")
    login.add_argument("--channel", choices=(*CHANNELS, "chromium"), help="Chrome/Edge 的安装通道")
    login.add_argument("--executable-path", type=Path, help="自定义浏览器可执行文件")
    sub.add_parser("browsers", help="查看支持的浏览器和本机可用状态")
    doctor = sub.add_parser("doctor", help="本地诊断，默认不读取会话内容")
    doctor.add_argument("--verify-login", action="store_true", help="显式校验已保存的登录态")
    skill = sub.add_parser("skill", help="安装 Agent Skill")
    skill_sub = skill.add_subparsers(dest="action", required=True)
    install = skill_sub.add_parser("install")
    install.add_argument("--destination", type=Path, help="自定义技能目录")
    auth = sub.add_parser("auth", help="查看会话状态")
    auth_sub = auth.add_subparsers(dest="action", required=True)
    status = auth_sub.add_parser("status")
    status.add_argument("--offline", action="store_true", help="只检查本地是否存有会话")
    sub.add_parser("logout", help="删除本工具保存的会话")
    api = sub.add_parser("api", help="启动 REST API 服务")
    api.add_argument("--port", type=int, default=8010)
    mcp = sub.add_parser("mcp", help="启动兼容工具名称的 MCP 服务，需要安装 mcp extra")
    mcp.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    mcp.add_argument("--port", type=int, default=8001)
    feed = sub.add_parser("feed", help="读取首页内容")
    pagination(feed)
    profile = sub.add_parser("profile", help="读取本人主页信息与动态")
    profile.add_argument(
        "--limit", type=positive, choices=range(1, 101), default=10, metavar="1..100"
    )
    media = sub.add_parser("media", help="本地媒体预检与上传")
    media_sub = media.add_subparsers(dest="action", required=True)
    for action in ("inspect", "upload"):
        item = media_sub.add_parser(action)
        item.add_argument("path", type=Path)
        item.add_argument("--kind", choices=("image", "video"), default="image")
        if action == "upload":
            item.add_argument("--dry-run", action="store_true")
    search = sub.add_parser("search", help="搜索社区帖子、用户、话题或游戏")
    search.add_argument("keyword")
    search.add_argument("--type", choices=("post", "user", "topic", "game"), default="post")
    pagination(search)
    games = sub.add_parser("games", help="查询小黑盒账号内的游戏记录")
    games.add_argument("--query", default="")
    pagination(games)
    review = sub.add_parser("review", help="个人评分和短评的查询、发布、修改、删除")
    actions = review.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--platform", default="steam", help="小黑盒内部平台标识，默认 steam")
    listing.add_argument(
        "--summary", action="store_true", help="只取游戏名称和个人评分，不逐款获取完整短评"
    )
    pagination(listing)
    for action in ("get", "create", "edit", "delete"):
        command = actions.add_parser(action)
        command.add_argument("appid", help="小黑盒游戏 ID")
        if action in ("create", "edit"):
            command.add_argument(
                "--score",
                type=int,
                choices=range(1, 6),
                required=action == "create",
                help="个人评分：1 到 5 星整数",
            )
            content_options(command, required=action == "create")
        if action != "get":
            command.add_argument(
                "--dry-run", action="store_true", help="读取当前记录后展示计划，不提交"
            )
    posts = sub.add_parser("post", help="读取、发布、修改和删除帖子")
    actions = posts.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    pagination(listing)
    get = actions.add_parser("get")
    get.add_argument("post_id")
    get.add_argument("--draft", action="store_true", help="读取本人草稿编辑数据")
    pagination(get)
    for action in ("create", "edit"):
        command = actions.add_parser(action)
        if action == "edit":
            command.add_argument("post_id")
        command.add_argument("--title", required=True)
        command.add_argument("--tag", type=int, default=11, help="内容分类 ID，默认文章 11")
        command.add_argument("--kind", choices=("article", "image_text"), default="article")
        command.add_argument("--image", type=Path, action="append", default=[])
        selections_options(command)
        content_options(command, required=False)
        command.add_argument("--publish", action="store_true", help="正式发布；默认保存草稿")
        command.add_argument("--dry-run", action="store_true")
    delete = actions.add_parser("delete")
    delete.add_argument("post_id")
    delete.add_argument("--dry-run", action="store_true")
    delete.add_argument("--draft", action="store_true", help="删除本人草稿")
    video = sub.add_parser("video", help="发布视频及封面，默认仅预览")
    video_sub = video.add_subparsers(dest="action", required=True)
    create = video_sub.add_parser("create")
    create.add_argument("path", type=Path)
    create.add_argument("--title", required=True)
    create.add_argument("--cover", type=Path)
    create.add_argument("--publish", action="store_true")
    create.add_argument("--dry-run", action="store_true")
    content_options(create, required=False)
    selections_options(create)
    comments = sub.add_parser("comment", help="查看评论、发表评论和回复")
    actions = comments.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("post_id")
    listing.add_argument("--sort", choices=("hot", "oldest", "latest"), default="hot")
    pagination(listing)
    for action in ("create", "reply"):
        command = actions.add_parser(action)
        command.add_argument("post_id")
        content_options(command, required=False)
        command.add_argument("--image", type=Path, action="append", default=[])
        command.add_argument("--dry-run", action="store_true")
        if action == "reply":
            target = command.add_mutually_exclusive_group(required=True)
            target.add_argument("--reply-id")
            target.add_argument("--target-text", help="按完整评论正文定位，重复正文会报错")
            command.add_argument("--root-id")
    return root


def read_content(args):
    if getattr(args, "file", None):
        try:
            return args.file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise ValueError("无法读取 UTF-8 正文文件。") from None
    return getattr(args, "text", None)


async def run(args):
    store = SessionStore()
    if args.command == "doctor":
        from .doctor import diagnose

        result = await diagnose(verify_login=args.verify_login, store=store)
        if result.get("login_error") == "auth":
            print("认证失败，登录校验已停止。", file=sys.stderr)
        return result
    if args.command == "skill":
        from .skill_install import install_skill

        return install_skill(args.destination)
    if args.command == "login":
        if args.cookie_file:
            if args.channel or args.executable_path:
                raise ValueError("导入 Cookie 时不能指定浏览器参数。")
            return await import_cookies(store, args.cookie_file)
        if args.browser or args.channel or args.executable_path:
            return await login_browser(
                store,
                timeout=args.timeout,
                browser_name=args.browser,
                channel=args.channel,
                executable_path=args.executable_path,
            )
        return await login_qr(store, timeout=args.timeout, qr_file=args.qr_file)
    if args.command == "browsers":
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            return {"items": inventory(playwright)}
    if args.command == "logout":
        store.delete()
        return {"authenticated": False, "local_session_deleted": True}
    if args.command == "auth":
        session = store.load()
        if args.offline or not session:
            return {"stored": bool(session), "authenticated": None, "checked_online": False}
        async with HeyboxAPI(session["cookies"]) as api:
            user = await verify(api, session["user_id"])
        return {"stored": True, "authenticated": True, "checked_online": True, "user_id": user}
    if args.command == "media" and args.action == "inspect":
        from .media import inspect_image, inspect_video

        item = inspect_image(args.path) if args.kind == "image" else await inspect_video(args.path)
        return item.preview()
    async with Operator(store) as operator:
        if args.command == "feed":
            return await operator.feed(offset=args.offset, limit=args.limit)
        if args.command == "profile":
            return await operator.profile(limit=args.limit)
        if args.command == "media":
            return await operator.upload_media(args.path, kind=args.kind, dry_run=args.dry_run)
        if args.command == "video":
            return await operator.write_video(
                args.title,
                args.path,
                content=read_content(args) or "",
                cover=args.cover,
                draft=False,
                dry_run=args.dry_run or not args.publish,
                communities=args.community,
                hashtags=args.hashtag,
            )
        if args.command == "search":
            return await operator.search(
                args.keyword, kind=args.type, offset=args.offset, limit=args.limit
            )
        if args.command == "games":
            return await operator.games(offset=args.offset, limit=args.limit, query=args.query)
        if args.command == "review":
            if args.action == "list":
                return await operator.reviews(
                    platform=args.platform,
                    offset=args.offset,
                    limit=args.limit,
                    summary=args.summary,
                )
            if args.action == "get":
                return present_review(await operator.review(args.appid))
            if args.action == "delete":
                return await operator.delete_review(args.appid, dry_run=args.dry_run)
            content = read_content(args)
            if args.action == "edit" and content is None and args.score is None:
                raise ValueError("修改短评至少需要 --score、--text 或 --file 之一。")
            return await operator.write_review(
                args.appid,
                score=args.score,
                content=content,
                edit=args.action == "edit",
                dry_run=args.dry_run,
            )
        if args.command == "post":
            if args.action == "list":
                return await operator.posts(offset=args.offset, limit=args.limit)
            if args.action == "get":
                if args.draft:
                    return await operator.edit_info(args.post_id)
                return await operator.post(args.post_id, offset=args.offset, limit=args.limit)
            if args.action == "delete":
                return await operator.delete_post(
                    args.post_id, dry_run=args.dry_run, draft=args.draft
                )
            return await operator.write_post(
                args.title,
                read_content(args) or "",
                tag=args.tag,
                draft=not args.publish,
                postid=getattr(args, "post_id", None),
                dry_run=args.dry_run,
                images=args.image,
                communities=args.community,
                hashtags=args.hashtag,
                post_kind=args.kind,
                base_dir=args.file.parent if args.file else None,
            )
        if args.command == "comment":
            if args.action == "list":
                return await operator.post(
                    args.post_id, offset=args.offset, limit=args.limit, sort=args.sort
                )
            if args.action == "reply" and args.reply_id and not args.root_id:
                raise ValueError("显式回复需要 --reply-id 与 --root-id。")
            return await operator.comment(
                args.post_id,
                read_content(args) or "",
                reply_id=getattr(args, "reply_id", None) or "-1",
                root_id=getattr(args, "root_id", None) or "-1",
                target_text=getattr(args, "target_text", None),
                images=args.image,
                dry_run=args.dry_run,
            )
    raise ValueError("未知命令。")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if legacy_command(argv):
            run_legacy(argv)
            return
        args = parser().parse_args(argv)
        if args.command == "mcp":
            try:
                from .mcp_server import serve
            except ImportError:
                raise OperatorError(
                    "请安装 xiaoheihe-cli[mcp] 后启动 MCP 服务。", "input"
                ) from None
            serve(transport=args.transport, port=args.port)
            return
        if args.command == "api":
            import uvicorn

            uvicorn.run("api_server:app", host="127.0.0.1", port=args.port)
            return
        result = asyncio.run(run(args))
        render(result, format=args.format, output=args.output)
    except OperatorError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False
            )
        )
        if exc.code == "auth":
            print("认证失败，操作已停止。", file=sys.stderr)
        raise SystemExit(exc.exit_code) from None
    except (ValueError, OSError, RuntimeError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": "input", "message": "输入或本地文件无效，请检查命令参数。"},
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"ok": False, "error": {"code": "cancelled", "message": "操作已取消。"}},
                ensure_ascii=False,
            )
        )
        raise SystemExit(130) from None
